import json
from datetime import datetime, date, timedelta

from flask import render_template, redirect, url_for, flash, request, jsonify, make_response
from flask_login import current_user

from app.constants import MILESTONE_COLOR
from app.project import project_bp
from app.project.forms import ProjectForm, MilestoneForm
from flask_login import login_required
from app.extensions import db
from app.models.project import Project, Milestone
from app.models.meeting import Meeting
from app.models.risk import Risk
from app.models.project_member import ProjectMember
from app.models.knowledge import Knowledge, PermissionRequest, PermissionItem, PermissionApplication
from app.models.user import User
from app.utils.pinyin import to_pinyin


@project_bp.route('/')
@login_required
def project_list():
    status = request.args.get('status', 'active')
    query = Project.query
    if status != 'all':
        query = query.filter_by(status=status)
    projects = query.order_by(Project.created_at.desc()).all()
    return render_template('project/list.html', projects=projects, cur_status=status)


@project_bp.route('/new', methods=['GET', 'POST'])
@login_required
def project_create():
    from app.models.project import MilestoneTemplate

    form = ProjectForm()
    form.parent_id.choices = [(0, '-- 无（顶级项目）--')] + [
        (p.id, p.name) for p in Project.query.filter_by(status='active').order_by(Project.name).all()]
    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()

    if form.validate_on_submit():
        project = Project(
            name=form.name.data,
            description=form.description.data,
            parent_id=form.parent_id.data or None,
            created_by=current_user.id,
        )
        db.session.add(project)
        db.session.flush()

        # Create milestones from form
        ms_names = request.form.getlist('ms_name')
        ms_dates = request.form.getlist('ms_date')
        for i, name in enumerate(ms_names):
            name = name.strip()
            if name:
                due_str = ms_dates[i] if i < len(ms_dates) and ms_dates[i] else ''
                due = date.fromisoformat(due_str) if due_str else None
                project.milestones.append(Milestone(name=name, due_date=due))

        db.session.commit()
        flash(f'项目「{project.name}」创建成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    return render_template('project/form.html', form=form, title='新建项目', templates=templates)


@project_bp.route('/milestone-templates', methods=['POST'])
@login_required
def milestone_template_action():
    """Create / edit / delete / copy milestone templates."""
    from app.models.project import MilestoneTemplate, MilestoneTemplateItem
    from app.constants import parse_offset

    action = request.form.get('action')

    if action == 'create':
        name = request.form.get('name', '').strip()
        if not name:
            flash('请输入模板名称', 'danger')
        elif MilestoneTemplate.query.filter_by(name=name).first():
            flash(f'模板 {name} 已存在', 'warning')
        else:
            tpl = MilestoneTemplate(name=name, description=request.form.get('description', '').strip() or None)
            item_names = request.form.getlist('item_name')
            item_offsets = request.form.getlist('item_offset')
            cumulative = 0
            for i, iname in enumerate(item_names):
                iname = iname.strip()
                if iname:
                    raw = item_offsets[i].strip() if i < len(item_offsets) and item_offsets[i] else '0'
                    cumulative += parse_offset(raw)
                    tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=cumulative, sort_order=i))
            db.session.add(tpl)
            db.session.commit()
            flash(f'模板 {name} 已创建', 'success')

    elif action == 'edit':
        tpl_id = request.form.get('template_id', type=int)
        tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
        if tpl:
            tpl.name = request.form.get('name', '').strip() or tpl.name
            tpl.description = request.form.get('description', '').strip() or None
            MilestoneTemplateItem.query.filter_by(template_id=tpl.id).delete()
            item_names = request.form.getlist('item_name')
            item_offsets = request.form.getlist('item_offset')
            cumulative = 0
            for i, iname in enumerate(item_names):
                iname = iname.strip()
                if iname:
                    raw = item_offsets[i].strip() if i < len(item_offsets) and item_offsets[i] else '0'
                    cumulative += parse_offset(raw)
                    tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=cumulative, sort_order=i))
            db.session.commit()
            flash(f'模板 {tpl.name} 已更新', 'success')

    elif action == 'copy':
        tpl_id = request.form.get('template_id', type=int)
        tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
        if tpl:
            new_name = f'{tpl.name}（副本）'
            idx = 2
            while MilestoneTemplate.query.filter_by(name=new_name).first():
                new_name = f'{tpl.name}（副本{idx}）'
                idx += 1
            copy = MilestoneTemplate(name=new_name, description=tpl.description)
            for item in tpl.items:
                copy.items.append(MilestoneTemplateItem(name=item.name, offset_days=item.offset_days, sort_order=item.sort_order))
            db.session.add(copy)
            db.session.commit()
            flash(f'已复制为 {new_name}', 'success')

    elif action == 'delete':
        tpl_id = request.form.get('template_id', type=int)
        tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
        if tpl:
            db.session.delete(tpl)
            db.session.commit()
            flash(f'模板 {tpl.name} 已删除', 'success')

    next_url = request.form.get('next') or request.args.get('next')
    return redirect(next_url) if next_url else redirect(request.referrer or url_for('project.project_list'))


@project_bp.route('/api/template/<int:tpl_id>')
@login_required
def api_template(tpl_id):
    from app.models.project import MilestoneTemplate
    tpl = db.session.get(MilestoneTemplate, tpl_id)
    if not tpl:
        return jsonify(ok=False), 404
    return jsonify(ok=True, items=[
        {'name': item.name, 'offset_days': item.offset_days}
        for item in tpl.items
    ])


@project_bp.route('/api/templates', methods=['GET', 'POST'])
@login_required
def api_templates():
    """List / create / delete milestone templates (accessible to all users)."""
    from app.models.project import MilestoneTemplate, MilestoneTemplateItem
    from app.constants import parse_offset

    if request.method == 'POST':
        data = request.get_json() or {}
        action = data.get('action')
        if action == 'create':
            name = (data.get('name') or '').strip()
            if not name:
                return jsonify(ok=False, msg='名称不能为空')
            if MilestoneTemplate.query.filter_by(name=name).first():
                return jsonify(ok=False, msg=f'模板 {name} 已存在')
            tpl = MilestoneTemplate(name=name, description=(data.get('description') or '').strip() or None)
            cumulative = 0
            for i, item in enumerate(data.get('items', [])):
                iname = (item.get('name') or '').strip()
                if iname:
                    cumulative += parse_offset(item.get('offset', 0))
                    tpl.items.append(MilestoneTemplateItem(name=iname, offset_days=cumulative, sort_order=i))
            db.session.add(tpl)
            db.session.commit()
            return jsonify(ok=True, id=tpl.id)
        elif action == 'copy':
            tpl_id = data.get('id')
            tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
            if not tpl:
                return jsonify(ok=False, msg='模板不存在')
            new_name = f'{tpl.name}（副本）'
            idx = 2
            while MilestoneTemplate.query.filter_by(name=new_name).first():
                new_name = f'{tpl.name}（副本{idx}）'
                idx += 1
            copy = MilestoneTemplate(name=new_name, description=tpl.description)
            for item in tpl.items:
                copy.items.append(MilestoneTemplateItem(name=item.name, offset_days=item.offset_days, sort_order=item.sort_order))
            db.session.add(copy)
            db.session.commit()
            return jsonify(ok=True, id=copy.id, name=new_name)
        elif action == 'delete':
            tpl_id = data.get('id')
            tpl = db.session.get(MilestoneTemplate, tpl_id) if tpl_id else None
            if tpl:
                db.session.delete(tpl)
                db.session.commit()
            return jsonify(ok=True)

    # GET: return all templates
    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()
    result = []
    for t in templates:
        items = []
        prev = 0
        for item in t.items:
            delta = item.offset_days - prev
            items.append({'name': item.name, 'offset': delta, 'cumulative': item.offset_days})
            prev = item.offset_days
        result.append({'id': t.id, 'name': t.name, 'description': t.description, 'items': items})
    return jsonify(ok=True, templates=result)


@project_bp.route('/<int:project_id>')
@login_required
def project_detail(project_id):
    from datetime import date as d_date
    from app.models.requirement import Requirement
    from app.models.todo import Todo, todo_requirements
    from sqlalchemy.orm import joinedload

    project = db.get_or_404(Project, project_id)
    today = d_date.today()

    # Requirements stats
    reqs = Requirement.query.filter_by(project_id=project_id, parent_id=None).order_by(Requirement.number).all()
    req_total = len(reqs)
    req_done = sum(1 for r in reqs if r.status in ('done', 'closed'))
    req_overdue = [r for r in reqs if r.due_date and r.due_date < today and r.status not in ('done', 'closed', 'cancelled')]

    # Open risks
    open_risks = Risk.query.filter_by(project_id=project_id, status='open').order_by(Risk.severity).all()

    # Key members
    key_members = ProjectMember.query.filter_by(project_id=project_id, is_key=True).all()

    # Recent completed todos (last 7 days)
    week_ago = today - timedelta(days=7)
    req_ids = [r.id for r in reqs]
    recent_done = []
    if req_ids:
        recent_done = Todo.query.filter(
            Todo.done_date >= week_ago
        ).join(todo_requirements, Todo.id == todo_requirements.c.todo_id).filter(
            todo_requirements.c.requirement_id.in_(req_ids)
        ).options(joinedload(Todo.user)).order_by(Todo.done_date.desc()).limit(10).all()

    return render_template('project/detail.html', project=project, today=today,
                           reqs=reqs, req_total=req_total, req_done=req_done,
                           req_overdue=req_overdue, open_risks=open_risks,
                           key_members=key_members, recent_done=recent_done,
                           milestone_color=MILESTONE_COLOR)


@project_bp.route('/<int:project_id>/follow', methods=['POST'])
@login_required
def toggle_follow(project_id):
    """Toggle follow/unfollow a project."""
    project = db.get_or_404(Project, project_id)
    if project in current_user.followed_projects.all():
        current_user.followed_projects.remove(project)
        followed = False
    else:
        current_user.followed_projects.append(project)
        followed = True
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True, followed=followed)
    return redirect(url_for('project.project_detail', project_id=project_id))


@project_bp.route('/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def project_edit(project_id):
    project = db.get_or_404(Project, project_id)
    form = ProjectForm(obj=project)
    form.parent_id.choices = [(0, '-- 无（顶级项目）--')] + [
        (p.id, p.name) for p in Project.query.filter(
            Project.status == 'active', Project.id != project_id).order_by(Project.name).all()]
    if not form.is_submitted():
        form.parent_id.data = project.parent_id or 0
    if form.validate_on_submit():
        project.name = form.name.data
        project.description = form.description.data
        project.parent_id = form.parent_id.data or None
        # Save milestones
        ms_names = request.form.getlist('ms_name')
        ms_dates = request.form.getlist('ms_date')
        Milestone.query.filter_by(project_id=project.id).delete()
        for i, name in enumerate(ms_names):
            name = name.strip()
            if name:
                due_str = ms_dates[i].strip() if i < len(ms_dates) and ms_dates[i] else ''
                due = date.fromisoformat(due_str) if due_str else None
                db.session.add(Milestone(
                    project_id=project.id, name=name,
                    due_date=due, status='active',
                ))
        db.session.commit()
        flash('项目更新成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    from app.models.project import MilestoneTemplate
    from app.models.project_member import ProjectMember
    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()
    members = ProjectMember.query.filter_by(project_id=project.id).all()
    member_ids = {m.user_id for m in members}
    available = [u for u in User.query.filter_by(is_active=True).order_by(User.name).all()
                 if u.id not in member_ids]
    return render_template('project/form.html', form=form, project=project,
                           templates=templates, members=members, available=available,
                           roles=ProjectMember.DEFAULT_ROLES,
                           title=f'编辑项目 - {project.name}')


@project_bp.route('/<int:project_id>/status', methods=['POST'])
@login_required
def project_status(project_id):
    project = db.get_or_404(Project, project_id)
    new_status = request.form.get('status')
    if new_status in Project.STATUS_LABELS:
        project.status = new_status
        db.session.commit()
        flash(f'项目已标记为「{project.status_label}」', 'success')
    return redirect(url_for('project.project_detail', project_id=project.id))


# --- Milestones ---

@project_bp.route('/<int:project_id>/milestones/new', methods=['GET', 'POST'])
@login_required
def milestone_create(project_id):
    project = db.get_or_404(Project, project_id)
    form = MilestoneForm()
    if form.validate_on_submit():
        ms = Milestone(project_id=project.id, name=form.name.data, due_date=form.due_date.data)
        db.session.add(ms)
        db.session.commit()
        flash(f'里程碑「{ms.name}」创建成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    return render_template('project/milestone_form.html', form=form, project=project, title='新建里程碑')


@project_bp.route('/milestones/<int:ms_id>/edit', methods=['GET', 'POST'])
@login_required
def milestone_edit(ms_id):
    ms = db.get_or_404(Milestone, ms_id)
    form = MilestoneForm(obj=ms)
    if form.validate_on_submit():
        ms.name = form.name.data
        ms.due_date = form.due_date.data
        db.session.commit()
        flash('里程碑更新成功', 'success')
        return redirect(url_for('project.project_detail', project_id=ms.project_id))
    return render_template('project/milestone_form.html', form=form, project=ms.project, title=f'编辑里程碑 - {ms.name}')


@project_bp.route('/milestones/<int:ms_id>/toggle', methods=['POST'])
@login_required
def milestone_toggle(ms_id):
    ms = db.get_or_404(Milestone, ms_id)
    ms.status = 'completed' if ms.status == 'active' else 'active'
    db.session.commit()
    flash(f'里程碑「{ms.name}」已标记为{"已完成" if ms.status == "completed" else "进行中"}', 'success')
    return redirect(url_for('project.project_detail', project_id=ms.project_id))


@project_bp.route('/milestones/<int:ms_id>/delete', methods=['POST'])
@login_required
def milestone_delete(ms_id):
    ms = db.get_or_404(Milestone, ms_id)
    project_id = ms.project_id
    if ms.requirements:
        flash('该里程碑下有关联需求，无法删除', 'danger')
    else:
        db.session.delete(ms)
        db.session.commit()
        flash('里程碑已删除', 'success')
    return redirect(url_for('project.project_detail', project_id=project_id))


# ---- Risk management ----

@project_bp.route('/<int:project_id>/risks')
@login_required
def risk_list(project_id):
    project = db.get_or_404(Project, project_id)
    status = request.args.get('status', '')
    severity = request.args.get('severity', '')

    query = Risk.query.filter_by(project_id=project_id).filter(Risk.deleted_at.is_(None))
    if status:
        query = query.filter_by(status=status)
    if severity:
        query = query.filter_by(severity=severity)
    risks = query.order_by(Risk.status, Risk.due_date).all()

    from app.models.requirement import Requirement
    reqs = Requirement.query.filter_by(project_id=project_id).order_by(Requirement.number).all()
    users = User.query.filter_by(is_active=True).order_by(User.name).all()

    return render_template('project/risks.html', project=project, risks=risks,
                           reqs=reqs, users=users, today=date.today(),
                           cur_status=status, cur_severity=severity)


@project_bp.route('/<int:project_id>/risks/add', methods=['POST'])
@login_required
def risk_add(project_id):
    db.get_or_404(Project, project_id)
    title = request.form.get('title', '').strip()
    if not title:
        flash('请输入风险标题', 'danger')
        return redirect(url_for('project.risk_list', project_id=project_id))

    risk = Risk(
        project_id=project_id,
        title=title,
        description=request.form.get('description', '').strip() or None,
        severity=request.form.get('severity', 'medium'),
        owner=request.form.get('owner', '').strip() or None,
        tracker_id=request.form.get('tracker_id', type=int) or None,
        requirement_id=request.form.get('requirement_id', type=int) or None,
        due_date=date.fromisoformat(request.form.get('due_date')) if request.form.get('due_date') else None,
        created_by=current_user.id,
    )
    db.session.add(risk)
    db.session.commit()
    flash('风险已登记', 'success')
    return redirect(url_for('project.risk_list', project_id=project_id))


@project_bp.route('/risks/<int:risk_id>/resolve', methods=['POST'])
@login_required
def risk_resolve(risk_id):
    risk = db.get_or_404(Risk, risk_id)
    resolution = request.form.get('resolution', '').strip()
    # If no resolution provided, use latest comment from last 24h
    if not resolution and risk.comments:
        from datetime import timedelta as _td
        latest = risk.comments[0]  # ordered desc
        if (datetime.utcnow() - latest.created_at).total_seconds() < 86400:
            resolution = latest.content
    if not resolution:
        flash('请填写解决方案（或先添加评论）', 'danger')
        return redirect(url_for('project.risk_list', project_id=risk.project_id))
    risk.status = 'resolved'
    risk.resolution = resolution
    risk.resolved_at = datetime.utcnow()
    from app.models.risk import RiskAuditLog
    db.session.add(RiskAuditLog(risk_id=risk.id, user_id=current_user.id, action='resolved', detail=resolution[:200]))
    db.session.commit()
    flash('风险已解决', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/risks/<int:risk_id>/close', methods=['POST'])
@login_required
def risk_close(risk_id):
    risk = db.get_or_404(Risk, risk_id)
    risk.status = 'closed'
    from app.models.risk import RiskAuditLog
    db.session.add(RiskAuditLog(risk_id=risk.id, user_id=current_user.id, action='closed'))
    db.session.commit()
    flash('风险已关闭', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/risks/<int:risk_id>/reopen', methods=['POST'])
@login_required
def risk_reopen(risk_id):
    risk = db.get_or_404(Risk, risk_id)
    risk.status = 'open'
    risk.resolution = None
    risk.resolved_at = None
    db.session.commit()
    flash('已重新打开', 'success')
    from app.models.risk import RiskAuditLog
    db.session.add(RiskAuditLog(risk_id=risk.id, user_id=current_user.id, action='reopened'))
    db.session.commit()
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/risks/<int:risk_id>/delete', methods=['POST'])
@login_required
def risk_delete(risk_id):
    """Soft delete a risk + audit log."""
    from app.models.risk import RiskAuditLog
    risk = db.get_or_404(Risk, risk_id)
    risk.deleted_at = datetime.utcnow()
    risk.deleted_by = current_user.id
    db.session.add(RiskAuditLog(risk_id=risk.id, user_id=current_user.id, action='deleted', detail=risk.title))
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True)
    flash('风险已删除', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/<int:project_id>/risks/export-csv')
@login_required
def risk_export_csv(project_id):
    """Export project risks as CSV."""
    import csv, io
    from flask import Response
    project = db.get_or_404(Project, project_id)
    risks = Risk.query.filter_by(project_id=project_id).order_by(Risk.created_at).all()
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(['ID', '标题', '严重度', '状态', '责任人', '跟踪人', '截止日期', '解决方案', '描述', '进展评论'])
    writer.writerow([0, '示例风险标题', '高(选填)', '未解决(选填)',
                     '责任人(选填)', '跟踪人(选填)', '2026-06-30(选填)', '(选填)',
                     '描述(选填)', '评论(选填,多条用换行) 此行为格式示例，导入时自动跳过'])
    for r in risks:
        comments = '\n'.join(f'{c.user.name} {c.created_at.strftime("%m-%d")}：{c.content}' for c in r.comments) if r.comments else ''
        writer.writerow([r.id, r.title, r.severity_label, r.status_label,
            r.owner or '', r.tracker.name if r.tracker else '',
            r.due_date.isoformat() if r.due_date else '', r.resolution or '', r.description or '', comments])
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=risks.csv'})


@project_bp.route('/<int:project_id>/risks/import-csv', methods=['POST'])
@login_required
def risk_import_csv(project_id):
    """Import risks from CSV."""
    import csv, io
    project = db.get_or_404(Project, project_id)
    file = request.files.get('csv_file')
    if not file or not file.filename.lower().endswith('.csv'):
        flash('请选择 CSV 文件', 'danger')
        return redirect(url_for('project.risk_list', project_id=project_id))
    raw = file.read()
    for enc in ('utf-8-sig', 'gbk', 'utf-8'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        flash('编码无法识别', 'danger')
        return redirect(url_for('project.risk_list', project_id=project_id))
    reader = csv.DictReader(io.StringIO(text))
    severity_rev = {v: k for k, v in Risk.SEVERITY_LABELS.items()}
    status_rev = {v: k for k, v in Risk.STATUS_LABELS.items()}
    user_map = {u.name: u.id for u in User.query.filter_by(is_active=True).all()}
    created = 0
    skipped = 0
    for row in reader:
        if (row.get('ID') or '').strip() == '0':
            continue
        title = (row.get('标题') or '').strip()
        if not title:
            continue
        rid = (row.get('ID') or '').strip()
        try:
            if rid and int(rid) > 0 and db.session.get(Risk, int(rid)):
                skipped += 1
                continue
        except ValueError:
            pass
        due_str = (row.get('截止日期') or '').strip()
        due = None
        if due_str:
            try:
                due = date.fromisoformat(due_str)
            except ValueError:
                pass
        if not due:
            due = date.today() + timedelta(days=14)
        tracker_name = (row.get('跟踪人') or '').strip()
        status_val = status_rev.get((row.get('状态') or '').strip(), 'open')
        resolution_text = (row.get('解决方案') or '').strip() or None
        risk = Risk(
            project_id=project_id, title=title,
            severity=severity_rev.get((row.get('严重度') or '').strip(), 'medium'),
            status=status_val,
            owner=(row.get('责任人') or '').strip() or None,
            tracker_id=user_map.get(tracker_name),
            due_date=due,
            description=(row.get('描述') or '').strip() or None,
            resolution=resolution_text,
            created_by=current_user.id,
        )
        if status_val == 'resolved' and resolution_text:
            risk.resolved_at = datetime.utcnow()
        db.session.add(risk)
        created += 1
    db.session.commit()
    msg = f'导入完成：{created} 条风险'
    if skipped:
        msg += f'，跳过 {skipped} 条重复'
    flash(msg, 'success')
    return redirect(url_for('project.risk_list', project_id=project_id))


@project_bp.route('/risks/<int:risk_id>/edit', methods=['POST'])
@login_required
def risk_edit(risk_id):
    """Edit risk details."""
    risk = db.get_or_404(Risk, risk_id)
    risk.title = request.form.get('title', risk.title).strip()
    risk.severity = request.form.get('severity', risk.severity)
    risk.owner = request.form.get('owner', '').strip() or None
    tracker_id = request.form.get('tracker_id', type=int)
    risk.tracker_id = tracker_id if tracker_id else None
    due = request.form.get('due_date', '')
    if due:
        try:
            risk.due_date = datetime.strptime(due, '%Y-%m-%d').date()
        except ValueError:
            pass
    db.session.commit()
    flash('风险已更新', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/risks/<int:risk_id>/comment', methods=['POST'])
@login_required
def risk_comment(risk_id):
    """Add progress comment to a risk."""
    from app.models.risk import RiskComment
    risk = db.get_or_404(Risk, risk_id)
    content = request.form.get('content', '').strip()[:500]
    if content:
        db.session.add(RiskComment(risk_id=risk.id, user_id=current_user.id, content=content))
        db.session.commit()
        flash('进展已记录', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


# ---- AI Risk Scan ----

@project_bp.route('/<int:project_id>/risks/ai-scan', methods=['POST'])
@login_required
def risk_ai_scan(project_id):
    """AI scans project data to identify potential risks."""
    from datetime import date, timedelta
    from collections import defaultdict
    from app.models.requirement import Requirement
    from app.models.todo import Todo, todo_requirements
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt
    from sqlalchemy.orm import joinedload

    project = db.get_or_404(Project, project_id)
    reqs = Requirement.query.filter_by(project_id=project_id).order_by(Requirement.number).all()
    today = date.today()

    # Existing risks (to avoid duplicates)
    existing_risks = Risk.query.filter_by(project_id=project_id, status='open').all()
    existing_titles = [r.title for r in existing_risks]

    # Build context
    lines = [f'项目：{project.name}，当前日期：{today}\n']

    # Existing open risks
    if existing_risks:
        lines.append('已登记的未解决风险（不要重复这些）：')
        for r in existing_risks:
            lines.append(f'- {r.title}')

    # Requirements overview with delay info
    lines.append('\n需求清单：')
    for r in reqs:
        due_info = ''
        if r.due_date:
            days_left = (r.due_date - today).days
            due_info = f'，已延期{-days_left}天' if days_left < 0 else f'，剩{days_left}天'
        assignee = r.assignee_display if hasattr(r, 'assignee_display') else ''
        lines.append(f'- [{r.number}] {r.title}（{r.status_label}，负责人：{assignee}{due_info}）')

    # Blocked and overdue todos
    project_req_ids = [r.id for r in reqs]
    if project_req_ids:
        blocked_todos = Todo.query.filter(
            Todo.status == 'todo', Todo.need_help == True
        ).join(todo_requirements, Todo.id == todo_requirements.c.todo_id).filter(
            todo_requirements.c.requirement_id.in_(project_req_ids)
        ).options(joinedload(Todo.user), joinedload(Todo.requirements)).all()

        if blocked_todos:
            lines.append('\n阻塞中的 Todo：')
            for t in blocked_todos:
                block_days = (today - t.created_date).days if t.created_date else 0
                reqs_str = ', '.join(r.number for r in t.requirements)
                reason = f'，原因：{t.blocked_reason}' if t.blocked_reason else ''
                lines.append(f'- {t.user.name}: {t.title}（{reqs_str}，阻塞{block_days}天{reason}）')

        # Stale requirements (no completed todo in last 7 days)
        week_ago = today - timedelta(days=7)
        active_req_ids = set()
        recent_todos = Todo.query.filter(
            Todo.done_date >= week_ago
        ).join(todo_requirements, Todo.id == todo_requirements.c.todo_id).filter(
            todo_requirements.c.requirement_id.in_(project_req_ids)
        ).all()
        for t in recent_todos:
            for r in t.requirements:
                active_req_ids.add(r.id)

        stale_reqs = [r for r in reqs if r.id not in active_req_ids
                      and r.status not in ('done', 'closed', 'cancelled')]
        if stale_reqs:
            lines.append('\n近7天无进展的需求：')
            for r in stale_reqs:
                lines.append(f'- [{r.number}] {r.title}（{r.status_label}，负责人：{r.assignee_display if hasattr(r, "assignee_display") else ""}）')

    prompt = get_prompt('risk_scan') + '\n\n' + '\n'.join(lines)
    result, raw = call_ollama(prompt)

    if isinstance(result, list) and result:
        return jsonify(ok=True, risks=result)
    elif isinstance(result, list) and not result:
        return jsonify(ok=True, risks=[], msg='AI 未识别到新风险')
    else:
        return jsonify(ok=False, raw=raw or '生成失败')


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
    import csv, io
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
    import csv, io
    project = db.get_or_404(Project, project_id)

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


# ---- Knowledge management ----

@project_bp.route('/<int:project_id>/knowledge', methods=['GET', 'POST'])
@login_required
def knowledge_list(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            db.session.add(Knowledge(
                project_id=project_id,
                title=request.form.get('title', '').strip(),
                link_type=request.form.get('link_type', 'doc'),
                biz_category=request.form.get('biz_category', '').strip() or None,
                link=request.form.get('link', '').strip() or None,
                created_by=current_user.id,
            ))
            db.session.commit()
            flash('知识条目已添加', 'success')
        elif action == 'edit':
            k = db.session.get(Knowledge, request.form.get('kid', type=int))
            if k and k.project_id == project_id:
                k.title = request.form.get('title', k.title).strip()
                k.link_type = request.form.get('link_type', k.link_type)
                k.biz_category = request.form.get('biz_category', '').strip() or None
                k.link = request.form.get('link', '').strip() or None
                db.session.commit()
                flash('已更新', 'success')
        elif action == 'pin':
            k = db.session.get(Knowledge, request.form.get('kid', type=int))
            if k and k.project_id == project_id:
                k.is_pinned = not k.is_pinned
                db.session.commit()
        elif action == 'delete':
            k = db.session.get(Knowledge, request.form.get('kid', type=int))
            if k and k.project_id == project_id:
                db.session.delete(k)
                db.session.commit()
                flash('已删除', 'success')
        return redirect(url_for('project.knowledge_list', project_id=project_id))

    items = Knowledge.query.filter_by(project_id=project_id).order_by(
        Knowledge.is_pinned.desc(), Knowledge.biz_category, Knowledge.updated_at.desc()).all()
    # Collect existing biz categories for quick-click
    existing_biz_cats = sorted(set(
        k.biz_category for k in items if k.biz_category))
    return render_template('project/knowledge.html', project=project, items=items,
                           link_types=Knowledge.LINK_TYPES,
                           existing_biz_cats=existing_biz_cats)


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
                app_record.approved_at = datetime.utcnow()
                app_record.approved_by = current_user.id
                db.session.commit()
                flash('已通过', 'success')
        elif action == 'bulk_approve' and is_pm:
            pending = PermissionApplication.query.join(PermissionItem).filter(
                PermissionItem.project_id == project_id,
                PermissionApplication.status == 'pending').all()
            for a in pending:
                a.status = 'approved'
                a.approved_at = datetime.utcnow()
                a.approved_by = current_user.id
            db.session.commit()
            flash(f'已批量通过 {len(pending)} 条', 'success')
        elif action == 'reject' and is_pm:
            app_record = db.session.get(PermissionApplication, request.form.get('app_id', type=int))
            if app_record and app_record.item.project_id == project_id:
                app_record.status = 'rejected'
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


# ---- Meeting minutes ----

@project_bp.route('/<int:project_id>/meetings')
@login_required
def meeting_list(project_id):
    project = db.get_or_404(Project, project_id)
    meetings = Meeting.query.filter_by(project_id=project_id).order_by(Meeting.date.desc()).all()
    return render_template('project/meetings.html', project=project, meetings=meetings)


@project_bp.route('/<int:project_id>/meetings/new', methods=['GET', 'POST'])
@login_required
def meeting_create(project_id):
    project = db.get_or_404(Project, project_id)
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        meeting_date = request.form.get('date', '')
        attendees = request.form.get('attendees', '').strip()
        content = request.form.get('content', '').strip()

        # Handle docx upload
        docx_file = request.files.get('docx_file')
        if docx_file and docx_file.filename and docx_file.filename.endswith('.docx'):
            from app.services.ai import extract_text_from_docx
            content = extract_text_from_docx(docx_file)

        if not title:
            flash('请输入会议标题', 'danger')
            return render_template('project/meeting_form.html', project=project)

        meeting = Meeting(
            project_id=project.id,
            title=title,
            date=datetime.strptime(meeting_date, '%Y-%m-%d').date() if meeting_date else date.today(),
            attendees=attendees,
            cc=request.form.get('cc', '').strip() or None,
            content=content,
            created_by=current_user.id,
        )
        db.session.add(meeting)
        db.session.commit()

        if request.form.get('auto_extract') == '1' and meeting.content:
            # Run AI extract immediately during creation
            from app.services.ai import call_ollama
            from app.services.prompts import get_prompt
            system_prompt = get_prompt('meeting_extract')
            parsed, raw = call_ollama(meeting.content, system_prompt=system_prompt)
            if parsed:
                meeting.ai_result = json.dumps(parsed, ensure_ascii=False)
                db.session.commit()
                flash(f'会议纪要「{meeting.title}」已创建，AI 润色提取完成，请确认润色结果', 'success')
            else:
                db.session.commit()
                flash(f'会议纪要已创建，AI 润色失败（{raw or "服务不可用"}），可稍后手动提取', 'warning')
        else:
            flash(f'会议纪要「{meeting.title}」创建成功', 'success')

        return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))
    return render_template('project/meeting_form.html', project=project)


@project_bp.route('/<int:project_id>/meetings/<int:meeting_id>/edit', methods=['GET', 'POST'])
@login_required
def meeting_edit(project_id, meeting_id):
    project = db.get_or_404(Project, project_id)
    meeting = db.get_or_404(Meeting, meeting_id)
    if request.method == 'POST':
        meeting.title = request.form.get('title', '').strip() or meeting.title
        meeting_date = request.form.get('date', '')
        if meeting_date:
            meeting.date = datetime.strptime(meeting_date, '%Y-%m-%d').date()
        meeting.attendees = request.form.get('attendees', '').strip()
        meeting.content = request.form.get('content', '').strip()
        db.session.commit()
        flash('会议纪要已更新', 'success')
        return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))
    return render_template('project/meeting_edit.html', project=project, meeting=meeting)


@project_bp.route('/<int:project_id>/meetings/<int:meeting_id>', methods=['GET', 'POST'])
@login_required
def meeting_detail(project_id, meeting_id):
    project = db.get_or_404(Project, project_id)
    meeting = db.get_or_404(Meeting, meeting_id)

    # POST = save edits
    if request.method == 'POST':
        meeting.title = request.form.get('title', '').strip() or meeting.title
        meeting_date = request.form.get('date', '')
        if meeting_date:
            meeting.date = datetime.strptime(meeting_date, '%Y-%m-%d').date()
        meeting.attendees = request.form.get('attendees', '').strip()
        meeting.cc = request.form.get('cc', '').strip()
        content = request.form.get('content', '').strip()
        if content:
            meeting.content = content
        db.session.commit()
        flash('会议纪要已保存', 'success')
        return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))

    ai_data = None
    if meeting.ai_result:
        try:
            ai_data = json.loads(meeting.ai_result)
        except json.JSONDecodeError:
            ai_data = None

    # Linked risks from this meeting
    linked_risks = Risk.query.filter_by(meeting_id=meeting.id).order_by(Risk.created_at).all()

    return render_template('project/meeting_detail.html', project=project, meeting=meeting,
                           ai_data=ai_data, linked_risks=linked_risks)


@project_bp.route('/<int:project_id>/meetings/<int:meeting_id>/extract', methods=['POST'])
@login_required
def meeting_extract(project_id, meeting_id):
    project = db.get_or_404(Project, project_id)
    meeting = db.get_or_404(Meeting, meeting_id)

    if not meeting.content or not meeting.content.strip():
        flash('会议纪要内容为空，无法提取', 'danger')
        return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))

    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    system_prompt = get_prompt('meeting_extract')
    # Build full context with meeting metadata
    context_lines = [
        f'会议标题：{meeting.title}',
        f'会议日期：{meeting.date.strftime("%Y-%m-%d") if meeting.date else "未知"}',
        f'召集人：{meeting.creator.name}',
    ]
    if meeting.attendees:
        context_lines.append(f'与会人：{meeting.attendees}')
    if meeting.cc:
        context_lines.append(f'抄送人：{meeting.cc}')
    context_lines.append(f'\n会议内容：\n{meeting.content}')
    full_text = '\n'.join(context_lines)
    parsed, raw = call_ollama(full_text, system_prompt=system_prompt)

    if parsed is None:
        flash('AI 提取失败，请稍后重试。' + (f' ({raw})' if raw else ''), 'danger')
        return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))

    # Save AI result (polished content saved only when user accepts)
    meeting.ai_result = json.dumps(parsed, ensure_ascii=False)
    db.session.commit()
    flash('AI 润色提取完成', 'success')
    return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))


@project_bp.route('/<int:project_id>/meetings/<int:meeting_id>/accept-polish', methods=['POST'])
@login_required
def meeting_accept_polish(project_id, meeting_id):
    """Accept AI polished content, write back to meeting.content."""
    meeting = db.get_or_404(Meeting, meeting_id)
    if meeting.ai_result:
        parsed = json.loads(meeting.ai_result)
        if parsed.get('polished'):
            meeting.content = parsed['polished']
            db.session.commit()
            return jsonify(ok=True)
    return jsonify(ok=False, msg='无润色内容')


@project_bp.route('/<int:project_id>/meetings/<int:meeting_id>/apply', methods=['POST'])
@login_required
def meeting_apply(project_id, meeting_id):
    project = db.get_or_404(Project, project_id)
    meeting = db.get_or_404(Meeting, meeting_id)

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, msg='无效的请求数据'), 400

    created_counts = {'todos': 0, 'requirements': 0, 'risks': 0}

    # Create Todos as low-severity risks (遗留问题)
    for item in data.get('todos', []):
        assignee_name = (item.get('assignee') or '').strip()
        assignee = User.query.filter_by(name=assignee_name, is_active=True).first() if assignee_name else None
        # Parse deadline
        deadline_str = (item.get('deadline') or '').strip()
        try:
            due = date.fromisoformat(deadline_str)
        except (ValueError, TypeError):
            due = date.today() + timedelta(days=7)
        risk = Risk(
            project_id=project.id,
            title=item.get('title', ''),
            severity='low',
            due_date=due,
            meeting_id=meeting.id,
            created_by=current_user.id,
            tracker_id=assignee.id if assignee else current_user.id,
        )
        db.session.add(risk)
        created_counts['todos'] += 1

    # Create Requirements
    from app.models.requirement import Requirement
    for item in data.get('requirements', []):
        req = Requirement(
            number=Requirement.generate_number(),
            project_id=project.id,
            title=item.get('title', ''),
            description=item.get('description', ''),
            priority=item.get('priority', 'medium'),
            source='meeting',
            created_by=current_user.id,
        )
        db.session.add(req)
        created_counts['requirements'] += 1

    # Create Risks with tracker
    for item in data.get('risks', []):
        deadline_str = (item.get('deadline') or '').strip()
        try:
            due = date.fromisoformat(deadline_str)
        except (ValueError, TypeError):
            due = date.today() + timedelta(days=7)
        risk = Risk(
            project_id=project.id,
            title=item.get('title', ''),
            severity=item.get('severity', 'medium'),
            due_date=due,
            meeting_id=meeting.id,
            created_by=current_user.id,
            tracker_id=current_user.id,
        )
        db.session.add(risk)
        created_counts['risks'] += 1

    # Clear ai_result so the panel disappears after reload
    meeting.ai_result = None
    db.session.commit()

    parts = []
    if created_counts['todos']:
        parts.append(f"{created_counts['todos']} 个待办")
    if created_counts['requirements']:
        parts.append(f"{created_counts['requirements']} 个需求")
    if created_counts['risks']:
        parts.append(f"{created_counts['risks']} 个风险")

    msg = '已创建 ' + '、'.join(parts) if parts else '未选择任何项目'
    return jsonify(ok=True, msg=msg)
