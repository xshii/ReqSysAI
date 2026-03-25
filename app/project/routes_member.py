"""Project member routes for the project blueprint."""
from flask import flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.project import project_bp

# ---- Project members ----

@project_bp.route('/<int:project_id>/members', methods=['GET', 'POST'])
@login_required
def member_list(project_id):
    project = db.get_or_404(Project, project_id)
    can_edit = current_user.is_admin or current_user.has_role('PM', 'PL', 'FO')
    if request.method == 'POST' and can_edit:
        action = request.form.get('action')
        if action == 'add':
            member_name = request.form.get('member_name', '').strip()
            role = request.form.get('project_role', 'DEV').strip()
            if member_name:
                # Try to find internal user by name
                user = User.query.filter_by(name=member_name, is_active=True).first()
                if user:
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
        elif action == 'toggle_key' and can_edit:
            member_id = request.form.get('member_id', type=int)
            m = db.session.get(ProjectMember, member_id)
            if m and m.project_id == project_id:
                m.is_key = not m.is_key
                db.session.commit()
        return redirect(url_for('project.member_list', project_id=project_id))

    members = ProjectMember.query.filter_by(project_id=project_id).all()
    all_users = User.query.filter_by(is_active=True).order_by(User.name).all()
    member_ids = {m.user_id for m in members}
    available = [u for u in all_users if u.id not in member_ids]
    return render_template('project/members.html', project=project, members=members,
                           available=available, roles=ProjectMember.DEFAULT_ROLES, can_edit=can_edit,
                           is_pm=can_edit)


# ---- Member CSV import/export ----

@project_bp.route('/<int:project_id>/members/export-csv')
@login_required
def member_export_csv(project_id):
    """Export project members as CSV."""
    import csv
    import io
    project = db.get_or_404(Project, project_id)
    members = ProjectMember.query.filter_by(project_id=project_id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', '姓名', '工号', '角色'])
    # Demo row (id=0)
    writer.writerow([0, '张三', 'a00123456', 'DEV(选填:PM/PL/DEV/TE/QA/UI) 此行为格式示例，导入时自动跳过'])
    for m in members:
        if m.user:
            writer.writerow([m.id, m.user.name, m.user.employee_id, m.project_role])
        else:
            writer.writerow([m.id, m.external_name or '', m.external_eid or '', m.project_role])

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    from urllib.parse import quote
    resp.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(project.name + '_members.csv')}"
    return resp


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
