"""Project member routes for the project blueprint."""
from flask import flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.project import project_bp
from app.project.routes import _check_project_access

# Domain keyword → project role mapping (checked first)
_DOMAIN_ROLE_MAP = [
    (['测试', 'test', 'TE'], 'TE'),
    (['质量', 'QA', 'quality'], 'QA'),
    (['产品', 'product', 'PM'], 'PM'),
    (['架构', 'architect'], 'PL'),
    (['设计', 'UI', 'UX', 'design'], 'UI'),
]

# System role → project role fallback
_SYS_ROLE_MAP = {
    'SE': 'DEV', 'DE': 'DEV', 'MDE': 'DEV', 'Committer': 'DEV',
    'TE': 'TE', 'QA': 'QA', 'PM': 'PM', 'PL': 'PL',
    'FO': 'PL', 'SEC': 'DEV', 'Admin': 'DEV',
}


def _default_project_role(user):
    """Derive project role from user's domain first, then system roles."""
    if not user:
        return 'DEV'
    # 1. Match by domain keywords
    domain = (user.domain or '').lower()
    if domain:
        for keywords, role in _DOMAIN_ROLE_MAP:
            if any(kw.lower() in domain for kw in keywords):
                return role
    # 2. Fallback to system role
    for r in (user.roles or []):
        if r.name in _SYS_ROLE_MAP:
            return _SYS_ROLE_MAP[r.name]
    return 'DEV'


# ---- Project members ----

@project_bp.route('/<int:project_id>/members', methods=['GET', 'POST'])
@login_required
def member_list(project_id):
    project = db.get_or_404(Project, project_id)
    denied = _check_project_access(project)
    if denied:
        return denied
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            member_name = request.form.get('member_name', '').strip()
            role = request.form.get('project_role', '').strip()
            if member_name:
                # Try to find internal user by name
                user = User.query.filter_by(name=member_name, is_active=True).first()
                if user:
                    if not role:
                        role = _default_project_role(user)
                    if not ProjectMember.query.filter_by(project_id=project_id, user_id=user.id).first():
                        db.session.add(ProjectMember(project_id=project_id, user_id=user.id, project_role=role))
                        db.session.commit()
                        flash(f'{user.name} 已添加', 'success')
                    else:
                        flash(f'{user.name} 已在项目中', 'warning')
                else:
                    # External member
                    if not ProjectMember.query.filter_by(project_id=project_id, external_name=member_name).first():
                        db.session.add(ProjectMember(project_id=project_id, external_name=member_name, project_role=role))
                        db.session.commit()
                        flash(f'外部成员 {member_name} 已添加', 'success')
        elif action == 'remove':
            member_id = request.form.get('member_id', type=int)
            m = db.session.get(ProjectMember, member_id)
            if m and m.project_id == project_id:
                db.session.delete(m)
                db.session.commit()
                flash('成员已移除', 'success')
        elif action == 'role':
            member_id = request.form.get('member_id', type=int)
            new_role = request.form.get('project_role', 'DEV')
            m = db.session.get(ProjectMember, member_id)
            if m and m.project_id == project_id:
                m.project_role = new_role
                db.session.commit()
                flash('角色已更新', 'success')
        elif action == 'toggle_key':
            member_id = request.form.get('member_id', type=int)
            m = db.session.get(ProjectMember, member_id)
            if m and m.project_id == project_id:
                m.is_key = not m.is_key
                db.session.commit()
        next_url = request.form.get('next') or url_for('project.member_list', project_id=project_id)
        return redirect(next_url)

    members = ProjectMember.query.filter_by(project_id=project_id).order_by(ProjectMember.sort_order).all()
    all_users = User.query.filter_by(is_active=True).order_by(User.name).all()
    member_ids = {m.user_id for m in members}
    available = [u for u in all_users if u.id not in member_ids]
    is_pm = project.owner_id == current_user.id or current_user.is_admin
    can_edit = is_pm  # same permission
    return render_template('project/members.html', project=project, members=members,
                           available=available, roles=ProjectMember.DEFAULT_ROLES,
                           is_pm=is_pm, can_edit=can_edit)


@project_bp.route('/<int:project_id>/members/ajax', methods=['POST'])
@login_required
def member_ajax(project_id):
    """AJAX member operations: add/remove/role/toggle_key. Returns JSON."""
    project = db.get_or_404(Project, project_id)
    denied = _check_project_access(project)
    if denied:
        return jsonify(ok=False, msg='无权限'), 403
    data = request.get_json() or {}
    action = data.get('action')
    if action == 'add':
        member_name = (data.get('member_name') or '').strip()
        role = (data.get('project_role') or '').strip()
        if not member_name:
            return jsonify(ok=False, msg='请输入成员名')
        user = User.query.filter_by(name=member_name, is_active=True).first()
        if user:
            if not role:
                role = _default_project_role(user)
            if ProjectMember.query.filter_by(project_id=project_id, user_id=user.id).first():
                return jsonify(ok=False, msg=f'{user.name} 已在项目中')
            m = ProjectMember(project_id=project_id, user_id=user.id, project_role=role)
            db.session.add(m)
            db.session.commit()
            return jsonify(ok=True, member={
                'id': m.id, 'name': user.name, 'group': user.group or '',
                'role': role, 'is_key': m.is_key, 'user_id': user.id,
            })
        else:
            if ProjectMember.query.filter_by(project_id=project_id, external_name=member_name).first():
                return jsonify(ok=False, msg=f'{member_name} 已在项目中')
            m = ProjectMember(project_id=project_id, external_name=member_name, project_role=role)
            db.session.add(m)
            db.session.commit()
            return jsonify(ok=True, member={
                'id': m.id, 'name': member_name, 'group': '',
                'role': role, 'is_key': m.is_key, 'user_id': None,
            })
    elif action == 'remove':
        member_id = data.get('member_id')
        m = db.session.get(ProjectMember, member_id)
        if m and m.project_id == project_id:
            uid = m.user_id
            name = m.display_name
            db.session.delete(m)
            db.session.commit()
            return jsonify(ok=True, user_id=uid, name=name)
        return jsonify(ok=False, msg='成员不存在')
    elif action == 'role':
        member_id = data.get('member_id')
        new_role = data.get('project_role', 'DEV')
        m = db.session.get(ProjectMember, member_id)
        if m and m.project_id == project_id:
            m.project_role = new_role
            db.session.commit()
            return jsonify(ok=True)
        return jsonify(ok=False, msg='成员不存在')
    elif action == 'toggle_key':
        member_id = data.get('member_id')
        m = db.session.get(ProjectMember, member_id)
        if m and m.project_id == project_id:
            m.is_key = not m.is_key
            db.session.commit()
            return jsonify(ok=True, is_key=m.is_key)
        return jsonify(ok=False, msg='成员不存在')
    return jsonify(ok=False, msg='未知操作')


# ---- Member CSV import/export ----

@project_bp.route('/<int:project_id>/members/export-csv')
@login_required
def member_export_csv(project_id):
    """Export project members as CSV."""
    import csv
    import io
    project = db.get_or_404(Project, project_id)
    members = ProjectMember.query.filter_by(project_id=project_id).order_by(ProjectMember.sort_order).all()

    from datetime import date as _date

    output = io.StringIO()
    output.write('\ufeff')  # BOM for Excel
    writer = csv.writer(output)
    writer.writerow(['id', '姓名', '工号', '角色'])
    # Demo row (id=0)
    writer.writerow([0, '张三', 'a00123456', 'DEV(选填:PM/PL/DEV/TE/QA/UI) 此行为格式示例，导入时自动跳过'])
    for m in members:
        if m.user:
            writer.writerow([m.id, m.user.name, m.user.employee_id, m.project_role])
        else:
            writer.writerow([m.id, m.external_name or '', m.external_eid or '', m.project_role])

    from flask import Response
    from urllib.parse import quote
    fname = f"{project.name}_项目成员_{_date.today().strftime('%Y%m%d')}.csv"
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(fname)}"})


@project_bp.route('/<int:project_id>/members/import-csv', methods=['POST'])
@login_required
def member_import_csv(project_id):
    """Import project members from CSV. Headers: id,姓名,工号,角色"""
    import csv
    import io
    _ = db.get_or_404(Project, project_id)

    file = request.files.get('csv_file')
    if not file or not file.filename:
        flash('请选择 CSV 文件', 'danger')
        return redirect(url_for('project.project_edit', project_id=project_id, tab='members'))

    try:
        text = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        file.seek(0)
        text = file.read().decode('gbk', errors='replace')

    reader = csv.DictReader(io.StringIO(text))
    created, updated = 0, 0
    for row in reader:
        if (row.get('id') or '').strip() == '0':
            continue  # Skip demo row
        name = (row.get('姓名') or '').strip()
        eid = (row.get('工号') or '').strip()
        role = (row.get('角色') or 'DEV').strip()
        if not name:
            continue

        # Try to find internal user
        user = None
        if eid:
            user = User.query.filter_by(employee_id=eid).first()
        if not user and name:
            user = User.query.filter_by(name=name, is_active=True).first()

        if user:
            existing = ProjectMember.query.filter_by(project_id=project_id, user_id=user.id).first()
            if existing:
                existing.project_role = role
                updated += 1
            else:
                db.session.add(ProjectMember(project_id=project_id, user_id=user.id, project_role=role))
                created += 1
        else:
            # External member
            existing = ProjectMember.query.filter_by(project_id=project_id, external_name=name).first()
            if existing:
                existing.project_role = role
                updated += 1
            else:
                db.session.add(ProjectMember(project_id=project_id, external_name=name,
                                             external_eid=eid, project_role=role))
                created += 1

    db.session.commit()
    flash(f'导入完成：新增 {created} 人，更新 {updated} 人', 'success')
    return redirect(url_for('project.project_edit', project_id=project_id, tab='members'))


@project_bp.route('/<int:project_id>/members/reorder', methods=['POST'])
@login_required
def member_reorder(project_id):
    """Reorder project members via drag-and-drop."""
    ids = request.json.get('ids', [])
    if not ids:
        return jsonify(ok=False), 400
    for i, mid in enumerate(ids):
        m = db.session.get(ProjectMember, int(mid))
        if m and m.project_id == project_id:
            m.sort_order = i
    db.session.commit()
    return jsonify(ok=True)
