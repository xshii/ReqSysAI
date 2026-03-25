"""Meeting minutes routes for the project blueprint."""
import json
from datetime import datetime, date, timedelta

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user, login_required

from app.project import project_bp
from app.extensions import db
from app.models.project import Project
from app.models.meeting import Meeting
from app.models.risk import Risk
from app.models.user import User
from app.project.routes import _resolve_owner_id


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
        t_owner = assignee.name if assignee else ''
        risk = Risk(
            project_id=project.id,
            title=item.get('title', ''),
            severity='low',
            owner=t_owner or None,
            owner_id=assignee.id if assignee else None,
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
        r_owner = (item.get('assignee') or '').strip()
        risk = Risk(
            project_id=project.id,
            title=item.get('title', ''),
            severity=item.get('severity', 'medium'),
            owner=r_owner or None,
            owner_id=_resolve_owner_id(r_owner),
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
