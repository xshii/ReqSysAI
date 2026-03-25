"""Permission management routes for the project blueprint."""
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user, login_required

from app.project import project_bp
from app.extensions import db
from app.models.project import Project
from app.models.knowledge import PermissionItem, PermissionApplication
from app.models.user import User
from app.utils.pinyin import to_pinyin


# ---- Permission management (catalog + applications) ----

@project_bp.route('/<int:project_id>/permissions', methods=['GET', 'POST'])
@login_required
def permission_list(project_id):
    project = db.get_or_404(Project, project_id)
    is_pm = current_user.is_admin or current_user.has_role('PM', 'PL', 'FO', 'LM', 'XM', 'HR')

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_item':
            db.session.add(PermissionItem(
                project_id=project_id,
                category=request.form.get('category', '').strip() or None,
                resource=request.form.get('resource', '').strip(),
                repo_path=request.form.get('repo_path', '').strip() or None,
                description=request.form.get('description', '').strip() or None,
                created_by=current_user.id,
            ))
            db.session.commit()
            flash('权限已登记', 'success')
        elif action == 'edit_item':
            item = db.session.get(PermissionItem, request.form.get('item_id', type=int))
            if item and item.project_id == project_id:
                item.category = request.form.get('category', '').strip() or None
                item.resource = request.form.get('resource', item.resource).strip()
                item.repo_path = request.form.get('repo_path', '').strip() or None
                item.description = request.form.get('description', '').strip() or None
                db.session.commit()
                flash('已更新', 'success')
        elif action == 'delete_item' and is_pm:
            item = db.session.get(PermissionItem, request.form.get('item_id', type=int))
            if item and item.project_id == project_id:
                db.session.delete(item)
                db.session.commit()
                flash('已删除', 'success')
        elif action == 'quick_apply':
            item = db.session.get(PermissionItem, request.form.get('item_id', type=int))
            if item and item.project_id == project_id:
                py = to_pinyin(current_user.name).split()[-1] if current_user.name else ''
                name = f"{current_user.name}({py}) {current_user.employee_id or ''}".strip()
                # Check duplicate
                exists = PermissionApplication.query.filter(
                    PermissionApplication.item_id == item.id,
                    PermissionApplication.applicant_name.contains(current_user.name),
                ).first()
                if exists:
                    flash('已在申请列表中', 'info')
                else:
                    db.session.add(PermissionApplication(
                        item_id=item.id, applicant_name=name,
                        submitted_by=current_user.id))
                    db.session.commit()
                    flash(f'已申请 {item.resource}', 'success')
            return redirect(url_for('project.permission_list', project_id=project_id))
        elif action == 'apply':
            item_ids = request.form.getlist('item_id')
            reason = request.form.get('reason', '').strip()
            people_text = request.form.get('people_list', '').strip()
            if not people_text:
                flash('请填写申请人', 'warning')
                return redirect(url_for('project.permission_list', project_id=project_id))
            count = 0
            for iid in item_ids:
                item = db.session.get(PermissionItem, int(iid))
                if not item or item.project_id != project_id:
                    continue
                db.session.add(PermissionApplication(
                    item_id=item.id, applicant_name=people_text,
                    reason=reason or None, submitted_by=current_user.id,
                ))
                count += 1
            if count:
                db.session.commit()
                flash(f'已申请 {count} 项权限', 'success')
            else:
                flash('未选择权限或已在申请列表中', 'info')
        elif action == 'approve' and is_pm:
            app_record = db.session.get(PermissionApplication, request.form.get('app_id', type=int))
            if app_record and app_record.item.project_id == project_id:
                app_record.status = 'approved'
                app_record.approved_at = datetime.now(timezone.utc)
                app_record.approved_by = current_user.id
                from app.services.notify import notify
                notify(app_record.submitted_by, 'permission',
                       f'权限申请「{app_record.item.resource}」已通过',
                       url_for('project.permission_list', project_id=project_id))
                from app.services.audit import log_audit
                log_audit('approve', 'permission', app_record.id, app_record.item.resource, app_record.applicant_name)
                db.session.commit()
                flash('已通过', 'success')
        elif action == 'bulk_approve' and is_pm:
            pending = PermissionApplication.query.join(PermissionItem).filter(
                PermissionItem.project_id == project_id,
                PermissionApplication.status == 'pending').all()
            from app.services.audit import log_audit
            for a in pending:
                a.status = 'approved'
                a.approved_at = datetime.now(timezone.utc)
                a.approved_by = current_user.id
                log_audit('approve', 'permission', a.id, a.item.resource, f'批量通过 {a.applicant_name}')
            db.session.commit()
            flash(f'已批量通过 {len(pending)} 条', 'success')
        elif action == 'reject' and is_pm:
            app_record = db.session.get(PermissionApplication, request.form.get('app_id', type=int))
            if app_record and app_record.item.project_id == project_id:
                app_record.status = 'rejected'
                from app.services.audit import log_audit
                log_audit('reject', 'permission', app_record.id, app_record.item.resource, app_record.applicant_name)
                db.session.commit()
                flash('已拒绝', 'success')
        elif action == 'delete_app':
            app_record = db.session.get(PermissionApplication, request.form.get('app_id', type=int))
            if app_record and app_record.item.project_id == project_id and (
                    app_record.submitted_by == current_user.id or is_pm):
                db.session.delete(app_record)
                db.session.commit()
                flash('已删除', 'success')
        return redirect(url_for('project.permission_list', project_id=project_id))

    # Query
    items = PermissionItem.query.filter_by(project_id=project_id).order_by(
        PermissionItem.category, PermissionItem.resource).all()
    apps = PermissionApplication.query.join(PermissionItem).filter(
        PermissionItem.project_id == project_id
    ).order_by(
        db.case((PermissionApplication.status == 'pending', 0),
                (PermissionApplication.status == 'approved', 1), else_=2),
        PermissionApplication.created_at.desc()).all()

    existing_categories = sorted(set(i.category for i in items if i.category))
    py = to_pinyin(current_user.name).split()[-1] if current_user.name else ''
    my_pinyin_name = f"{current_user.name}({py})" if py else current_user.name
    all_users = User.query.order_by(User.name).all()

    return render_template('project/permissions.html', project=project,
                           items=items, apps=apps, is_pm=is_pm,
                           existing_categories=existing_categories,
                           my_pinyin_name=my_pinyin_name, all_users=all_users)


@project_bp.route('/<int:project_id>/permissions/export-items')
@login_required
def permission_export_items(project_id):
    """Export permission catalog as CSV."""
    import csv, io
    from flask import Response
    project = db.get_or_404(Project, project_id)
    items = PermissionItem.query.filter_by(project_id=project_id).order_by(
        PermissionItem.category, PermissionItem.resource).all()
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(['权限ID', '分类', '群组', '代码仓/路径', '说明'])
    writer.writerow([0, 'SVN(示例)', 'group-xxx', 'repo/path', '此行为格式示例，导入时自动跳过'])
    for item in items:
        writer.writerow([item.id, item.category or '', item.resource,
                         item.repo_path or '', item.description or ''])
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=权限目录_{project.name}.csv'})


@project_bp.route('/<int:project_id>/permissions/export-apps')
@login_required
def permission_export_apps(project_id):
    """Export permission applications as CSV."""
    import csv, io
    from flask import Response
    project = db.get_or_404(Project, project_id)
    apps = PermissionApplication.query.join(PermissionItem).filter(
        PermissionItem.project_id == project_id
    ).order_by(PermissionApplication.created_at.desc()).all()
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(['申请ID', '群组', '分类', '申请人', '工号', '申请理由', '状态', '申请日期', '审批日期'])
    writer.writerow([0, 'group-xxx', 'SVN(示例)', '张三(zhangsan)', 'a00123456',
                     '开发需要', '待审批', '2026-01-01', '此行为格式示例，导入时自动跳过'])
    for a in apps:
        writer.writerow([
            a.id, a.item.resource, a.item.category or '',
            a.applicant_name, a.applicant_eid or '', a.reason or '',
            a.status_label,
            a.created_at.strftime('%Y-%m-%d') if a.created_at else '',
            a.approved_at.strftime('%Y-%m-%d') if a.approved_at else '',
        ])
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=申请记录_{project.name}.csv'})


def _read_csv(project_id):
    """Shared CSV reading logic. Returns (reader, redirect_response)."""
    import csv, io
    file = request.files.get('csv_file')
    if not file or not file.filename.lower().endswith('.csv'):
        flash('请选择 CSV 文件', 'danger')
        return None, redirect(url_for('project.permission_list', project_id=project_id))
    raw = file.read()
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        flash('编码无法识别', 'danger')
        return None, redirect(url_for('project.permission_list', project_id=project_id))
    return csv.DictReader(io.StringIO(text)), None


@project_bp.route('/<int:project_id>/permissions/import-items', methods=['POST'])
@login_required
def permission_import_items(project_id):
    """Import permission catalog from CSV."""
    db.get_or_404(Project, project_id)
    reader, err = _read_csv(project_id)
    if err:
        return err
    if not {'群组'}.issubset(set(reader.fieldnames or [])):
        flash('CSV 缺少必填列: 群组', 'danger')
        return redirect(url_for('project.permission_list', project_id=project_id))
    created, updated = 0, 0
    for row in reader:
        if (row.get('权限ID') or '').strip() == '0':
            continue
        resource = (row.get('群组') or '').strip()
        if not resource:
            continue
        category = (row.get('分类') or '').strip() or None
        existing = PermissionItem.query.filter_by(
            project_id=project_id, resource=resource, category=category).first()
        if existing:
            existing.repo_path = (row.get('代码仓/路径') or '').strip() or existing.repo_path
            existing.description = (row.get('说明') or '').strip() or existing.description
            updated += 1
        else:
            db.session.add(PermissionItem(
                project_id=project_id, category=category, resource=resource,
                repo_path=(row.get('代码仓/路径') or '').strip() or None,
                description=(row.get('说明') or '').strip() or None,
                created_by=current_user.id))
            created += 1
    db.session.commit()
    flash(f'权限目录导入完成：新增 {created}，更新 {updated}', 'success')
    return redirect(url_for('project.permission_list', project_id=project_id))


@project_bp.route('/<int:project_id>/permissions/import-apps', methods=['POST'])
@login_required
def permission_import_apps(project_id):
    """Import permission applications from CSV."""
    db.get_or_404(Project, project_id)
    reader, err = _read_csv(project_id)
    if err:
        return err
    if not {'群组', '申请人'}.issubset(set(reader.fieldnames or [])):
        flash('CSV 缺少必填列: 群组, 申请人', 'danger')
        return redirect(url_for('project.permission_list', project_id=project_id))
    status_rev = {v: k for k, v in PermissionApplication.STATUS_LABELS.items()}
    created = 0
    for row in reader:
        if (row.get('申请ID') or '').strip() == '0':
            continue
        resource = (row.get('群组') or '').strip()
        applicant = (row.get('申请人') or '').strip()
        if not resource or not applicant:
            continue
        category = (row.get('分类') or '').strip() or None
        item = PermissionItem.query.filter_by(
            project_id=project_id, resource=resource, category=category).first()
        if not item:
            item = PermissionItem(project_id=project_id, category=category,
                                  resource=resource, created_by=current_user.id)
            db.session.add(item)
            db.session.flush()
        exists = PermissionApplication.query.filter_by(
            item_id=item.id, applicant_name=applicant).first()
        if not exists:
            status = status_rev.get((row.get('状态') or '').strip(), 'pending')
            db.session.add(PermissionApplication(
                item_id=item.id, applicant_name=applicant,
                applicant_eid=(row.get('工号') or '').strip() or None,
                reason=(row.get('申请理由') or '').strip() or None,
                status=status, submitted_by=current_user.id))
            created += 1
    db.session.commit()
    flash(f'申请记录导入完成：新增 {created} 条', 'success')
    return redirect(url_for('project.permission_list', project_id=project_id))
