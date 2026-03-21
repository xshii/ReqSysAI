import json
from datetime import datetime, date

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user

from app.project import project_bp
from app.project.forms import ProjectForm, MilestoneForm
from flask_login import login_required
from app.extensions import db
from app.models.project import Project, Milestone
from app.models.meeting import Meeting
from app.models.risk import Risk
from app.models.user import User


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
    from datetime import timedelta

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
    project = db.get_or_404(Project, project_id)
    return render_template('project/detail.html', project=project)


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

    from datetime import date
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
        from datetime import datetime as dt
        try:
            risk.due_date = dt.strptime(due, '%Y-%m-%d').date()
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
