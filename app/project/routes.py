import json
from datetime import datetime, date, timedelta

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user

from app.project import project_bp
from app.project.forms import ProjectForm, MilestoneForm
from flask_login import login_required
from app.extensions import db
from app.models.project import Project, Milestone
from app.models.meeting import Meeting
from app.models.risk import Risk
from app.models.project_member import ProjectMember
from app.models.knowledge import Knowledge, PermissionRequest
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
    templates = MilestoneTemplate.query.order_by(MilestoneTemplate.name).all()

    if form.validate_on_submit():
        project = Project(
            name=form.name.data,
            description=form.description.data,
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
                due = ms_dates[i] if i < len(ms_dates) and ms_dates[i] else None
                project.milestones.append(Milestone(name=name, due_date=due))

        db.session.commit()
        flash(f'项目「{project.name}」创建成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    return render_template('project/form.html', form=form, title='新建项目', templates=templates)


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
                           key_members=key_members, recent_done=recent_done)


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
    if form.validate_on_submit():
        project.name = form.name.data
        project.description = form.description.data
        db.session.commit()
        flash('项目更新成功', 'success')
        return redirect(url_for('project.project_detail', project_id=project.id))
    return render_template('project/form.html', form=form, title=f'编辑项目 - {project.name}')


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

    query = Risk.query.filter_by(project_id=project_id)
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
        due_date=request.form.get('due_date') or None,
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
    if not resolution:
        flash('请填写解决方案', 'danger')
        return redirect(url_for('project.risk_list', project_id=risk.project_id))
    risk.status = 'resolved'
    risk.resolution = resolution
    risk.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('风险已解决', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/risks/<int:risk_id>/close', methods=['POST'])
@login_required
def risk_close(risk_id):
    risk = db.get_or_404(Risk, risk_id)
    risk.status = 'closed'
    db.session.commit()
    flash('风险已关闭', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/risks/<int:risk_id>/reopen', methods=['POST'])
@login_required
def risk_reopen(risk_id):
    risk = db.get_or_404(Risk, risk_id)
    risk.status = 'open'
    risk.resolved_at = None
    risk.resolution = None
    db.session.commit()
    flash('风险已重新打开', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


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
            user_id = request.form.get('user_id', type=int)
            ext_name = request.form.get('external_name', '').strip()
            role = request.form.get('project_role', 'DEV').strip()
            custom_role = request.form.get('custom_role', '').strip()
            if custom_role:
                role = custom_role
            if user_id:
                if not ProjectMember.query.filter_by(project_id=project_id, user_id=user_id).first():
                    db.session.add(ProjectMember(project_id=project_id, user_id=user_id, project_role=role))
                    db.session.commit()
                    flash('成员已添加', 'success')
            elif ext_name:
                ext_eid = request.form.get('external_eid', '').strip()
                db.session.add(ProjectMember(project_id=project_id, external_name=ext_name, external_eid=ext_eid, project_role=role))
                db.session.commit()
                flash(f'外部成员 {ext_name} 已添加', 'success')
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


# ---- Permission requests ----

@project_bp.route('/<int:project_id>/permissions', methods=['GET', 'POST'])
@login_required
def permission_list(project_id):
    project = db.get_or_404(Project, project_id)
    is_pm = current_user.is_admin or current_user.has_role('PM', 'PL', 'FO', 'LM', 'XM', 'HR')

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            db.session.add(PermissionRequest(
                project_id=project_id,
                category=request.form.get('category', '').strip() or None,
                resource=request.form.get('resource', '').strip(),
                repo_path=request.form.get('repo_path', '').strip() or None,
                description=request.form.get('description', '').strip() or None,
                applicants=request.form.get('applicants', '').strip(),
                submitter_id=current_user.id,
            ))
            db.session.commit()
            flash('权限申请已登记', 'success')
        elif action == 'apply':
            # Batch apply: check multiple permissions, for self or other
            prid_list = request.form.getlist('prid')
            apply_for = request.form.get('apply_for', 'self')  # self / other
            reason = request.form.get('reason', '').strip()
            if apply_for == 'self':
                py = to_pinyin(current_user.name).split()[-1] if current_user.name else ''
                eid = current_user.employee_id or ''
                entry = f"{current_user.name}({py}) {eid}"
            else:
                other_name = request.form.get('other_name', '').strip()
                other_eid = request.form.get('other_eid', '').strip()
                entry = other_name
                if other_eid:
                    entry += f" {other_eid}"
            if reason:
                entry += f" - {reason}"
            count = 0
            for prid in prid_list:
                pr = db.session.get(PermissionRequest, int(prid))
                if not pr or pr.project_id != project_id or pr.status != 'draft':
                    continue
                prev = pr.applicants or ''
                # Deduplicate by name
                name_check = current_user.name if apply_for == 'self' else other_name
                if name_check and name_check in prev:
                    continue
                pr.applicants = (prev + '\n' + entry).strip() if prev else entry
                count += 1
            if count:
                db.session.commit()
                flash(f'已申请 {count} 项权限', 'success')
            else:
                flash('未选择权限或已在申请列表中', 'info')
        elif action == 'edit':
            pr = db.session.get(PermissionRequest, request.form.get('prid', type=int))
            if pr and pr.project_id == project_id and pr.status == 'draft':
                pr.category = request.form.get('category', '').strip() or None
                pr.resource = request.form.get('resource', pr.resource).strip()
                pr.repo_path = request.form.get('repo_path', '').strip() or None
                pr.description = request.form.get('description', '').strip() or None
                pr.applicants = request.form.get('applicants', pr.applicants).strip()
                db.session.commit()
                flash('已更新', 'success')
        elif action == 'submit' and is_pm:
            pr = db.session.get(PermissionRequest, request.form.get('prid', type=int))
            if pr and pr.project_id == project_id and pr.status == 'draft':
                pr.status = 'submitted'
                pr.submitted_at = datetime.utcnow()
                db.session.commit()
                flash('已提交审批', 'success')
        elif action == 'approve' and is_pm:
            pr = db.session.get(PermissionRequest, request.form.get('prid', type=int))
            if pr and pr.project_id == project_id and pr.status == 'submitted':
                pr.status = 'approved'
                pr.approved_at = datetime.utcnow()
                db.session.commit()
                flash('审批完成', 'success')
        elif action == 'delete':
            pr = db.session.get(PermissionRequest, request.form.get('prid', type=int))
            if pr and pr.project_id == project_id and pr.status == 'draft' and (
                    pr.submitter_id == current_user.id or is_pm):
                db.session.delete(pr)
                db.session.commit()
                flash('已删除', 'success')
        return redirect(url_for('project.permission_list', project_id=project_id))

    items = PermissionRequest.query.filter_by(project_id=project_id).order_by(
        db.case((PermissionRequest.status == 'draft', 0),
                (PermissionRequest.status == 'submitted', 1), else_=2),
        PermissionRequest.category, PermissionRequest.resource,
        PermissionRequest.created_at.desc()).all()
    # Draft items for the apply modal checklist
    draft_items = [pr for pr in items if pr.status == 'draft']
    draft_resources = sorted(set(pr.resource for pr in draft_items))
    # Collect existing categories for quick-click
    existing_categories = sorted(set(
        pr.category for pr in items if pr.category))
    # Current user's pinyin name for display in "为我申请"
    py = to_pinyin(current_user.name).split()[-1] if current_user.name else ''
    my_pinyin_name = f"{current_user.name}({py})" if py else current_user.name
    # Users for internal member search in "为他人申请"
    all_users = User.query.order_by(User.name).all()
    return render_template('project/permissions.html', project=project, items=items,
                           is_pm=is_pm, draft_items=draft_items, draft_resources=draft_resources,
                           existing_categories=existing_categories,
                           my_pinyin_name=my_pinyin_name, all_users=all_users)


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
            content=content,
            created_by=current_user.id,
        )
        db.session.add(meeting)
        db.session.commit()
        flash(f'会议纪要「{meeting.title}」创建成功', 'success')
        return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))
    return render_template('project/meeting_form.html', project=project)


@project_bp.route('/<int:project_id>/meetings/<int:meeting_id>')
@login_required
def meeting_detail(project_id, meeting_id):
    project = db.get_or_404(Project, project_id)
    meeting = db.get_or_404(Meeting, meeting_id)
    ai_data = None
    if meeting.ai_result:
        try:
            ai_data = json.loads(meeting.ai_result)
        except json.JSONDecodeError:
            ai_data = None
    return render_template('project/meeting_detail.html', project=project, meeting=meeting, ai_data=ai_data)


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
    parsed, raw = call_ollama(meeting.content, system_prompt=system_prompt)

    if parsed is None:
        flash('AI 提取失败，请稍后重试。' + (f' ({raw})' if raw else ''), 'danger')
        return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))

    meeting.ai_result = json.dumps(parsed, ensure_ascii=False)
    db.session.commit()
    flash('AI 提取完成', 'success')
    return redirect(url_for('project.meeting_detail', project_id=project.id, meeting_id=meeting.id))


@project_bp.route('/<int:project_id>/meetings/<int:meeting_id>/apply', methods=['POST'])
@login_required
def meeting_apply(project_id, meeting_id):
    project = db.get_or_404(Project, project_id)
    meeting = db.get_or_404(Meeting, meeting_id)

    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, msg='无效的请求数据'), 400

    created_counts = {'todos': 0, 'requirements': 0, 'risks': 0}

    # Create Todos
    from app.models.todo import Todo
    for item in data.get('todos', []):
        todo = Todo(
            user_id=current_user.id,
            title=item.get('title', ''),
            created_date=date.today(),
        )
        db.session.add(todo)
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

    # Create Risks
    for item in data.get('risks', []):
        risk = Risk(
            project_id=project.id,
            title=item.get('title', ''),
            severity=item.get('severity', 'medium'),
            due_date=date.today(),
            created_by=current_user.id,
        )
        db.session.add(risk)
        created_counts['risks'] += 1

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
