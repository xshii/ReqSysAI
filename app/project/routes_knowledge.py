"""Knowledge management and AAR routes for the project blueprint."""
from datetime import date, timedelta

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from app.utils.api import api_ok, api_err
from flask_login import current_user, login_required

from app.extensions import db
from app.models.knowledge import AAR, Knowledge
from app.models.project import Project
from app.models.risk import Risk
from app.project import project_bp
from app.project.routes import _check_project_access, _resolve_owner_id

# ---- Knowledge management ----

@project_bp.route('/<int:project_id>/knowledge', methods=['GET', 'POST'])
@login_required
def knowledge_list(project_id):
    project = db.get_or_404(Project, project_id)
    denied = _check_project_access(project)
    if denied:
        return denied
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
    aars = AAR.query.filter_by(project_id=project_id).order_by(AAR.date.desc()).all()
    milestones = project.milestones
    from app.utils.recipients import compute_default_recipients
    aar_to, aar_cc = compute_default_recipients(project_id)
    return render_template('project/knowledge.html', project=project, items=items, aars=aars,
                           trigger_labels=AAR.TRIGGER_LABELS, ai_enabled=current_app.config.get('AI_ENABLED'),
                           link_types=Knowledge.LINK_TYPES,
                           existing_biz_cats=existing_biz_cats,
                           milestones=milestones, today=date.today(),
                           aar_default_to=aar_to, aar_default_cc=aar_cc)


# ---- AAR (After Action Review) ----

@project_bp.route('/<int:project_id>/aar', methods=['GET', 'POST'])
@login_required
def aar_list(project_id):
    project = db.get_or_404(Project, project_id)
    denied = _check_project_access(project)
    if denied:
        return denied

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            from datetime import date as date_cls
            date_str = request.form.get('date', '')
            try:
                aar_date = date_cls.fromisoformat(date_str) if date_str else date.today()
            except ValueError:
                aar_date = date.today()
            db.session.add(AAR(
                project_id=project_id,
                title=request.form.get('title', '').strip(),
                trigger=request.form.get('trigger', 'custom'),
                trigger_ref=request.form.get('trigger_ref', '').strip() or None,
                date=aar_date,
                participants=request.form.get('participants', '').strip() or None,
                goal=request.form.get('goal', '').strip() or None,
                result=request.form.get('result', '').strip() or None,
                analysis=request.form.get('analysis', '').strip() or None,
                action=request.form.get('action_items', '').strip() or None,
                created_by=current_user.id,
            ))
            db.session.commit()
            flash('AAR 已创建', 'success')
        elif action == 'edit':
            aar = db.session.get(AAR, request.form.get('aar_id', type=int))
            if aar and aar.project_id == project_id:
                aar.title = request.form.get('title', aar.title).strip()
                aar.trigger = request.form.get('trigger', aar.trigger)
                aar.trigger_ref = request.form.get('trigger_ref', '').strip() or None
                date_str = request.form.get('date', '')
                if date_str:
                    try:
                        aar.date = date.fromisoformat(date_str)
                    except ValueError:
                        pass
                aar.participants = request.form.get('participants', '').strip() or None
                aar.goal = request.form.get('goal', '').strip() or None
                aar.result = request.form.get('result', '').strip() or None
                aar.analysis = request.form.get('analysis', '').strip() or None
                aar.action = request.form.get('action_items', '').strip() or None
                aar.status = request.form.get('status', aar.status)
                db.session.commit()
                flash('已更新', 'success')
        elif action == 'delete':
            aar = db.session.get(AAR, request.form.get('aar_id', type=int))
            if aar and aar.project_id == project_id:
                db.session.delete(aar)
                db.session.commit()
                flash('已删除', 'success')
        return redirect(url_for('project.aar_list', project_id=project_id))

    items = AAR.query.filter_by(project_id=project_id).order_by(AAR.date.desc()).all()
    milestones = project.milestones
    return render_template('project/aar.html', project=project, items=items,
                           milestones=milestones, trigger_labels=AAR.TRIGGER_LABELS,
                           today=date.today(), ai_enabled=current_app.config.get('AI_ENABLED'))


@project_bp.route('/<int:project_id>/aar/ai-issues', methods=['POST'])
@login_required
def aar_ai_issues(project_id):
    """AI extracts remaining issues from AAR content."""
    db.get_or_404(Project, project_id)
    data = request.get_json() or {}
    goal = data.get('goal', '').strip()
    result = data.get('result', '').strip()
    analysis = data.get('analysis', '').strip()
    action = data.get('action', '').strip()

    if not (goal or result or analysis):
        return api_err(msg='请先填写目标/结果/差异分析')

    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt
    action_line = f'改进措施：{action}' if action else ''
    aar_date = data.get('aar_date', str(date.today()))
    tpl = get_prompt('aar_extract_issues')
    prompt = tpl.format(goal=goal or '未填写', result=result or '未填写',
                        analysis=analysis or '未填写', action_line=action_line,
                        aar_date=aar_date)

    result_data, _ = call_ollama(prompt)

    # Validate owner against system users
    from app.models.user import User
    user_names = {u.name for u in User.query.filter_by(is_active=True).all()}

    def _validate_issues(issues):
        for issue in issues:
            if isinstance(issue, dict):
                owner = (issue.get('owner') or '').strip()
                if owner and owner not in user_names:
                    issue['owner'] = ''  # Not a system user, clear it
        return issues

    # AI may return {"action":"...", "issues":[...]} or {"issues":[...]} or just [...]
    if isinstance(result_data, dict):
        issues = _validate_issues(result_data.get('issues', []))
        ai_action = result_data.get('action', '')
        return api_ok(issues=issues, action=ai_action)
    if isinstance(result_data, list):
        return api_ok(issues=_validate_issues(result_data), action='')
    return api_err(msg='AI服务暂不可用，正在紧急修复')


@project_bp.route('/<int:project_id>/aar/<int:aar_id>/save-action', methods=['POST'])
@login_required
def aar_save_action(project_id, aar_id):
    """Save AI-generated action back to AAR."""
    aar = db.session.get(AAR, aar_id)
    if aar and aar.project_id == project_id:
        data = request.get_json() or {}
        raw_action = data.get('action', '')
        if isinstance(raw_action, list):
            action_text = '\n'.join(
                a if isinstance(a, str) else (a.get('title') or a.get('content') or str(a))
                for a in raw_action
            ).strip()
        else:
            action_text = str(raw_action).strip()
        if action_text and not aar.action:
            aar.action = action_text
            db.session.commit()
            return api_ok()
    return api_err()


@project_bp.route('/<int:project_id>/aar/adopt-risks', methods=['POST'])
@login_required
def aar_adopt_risks(project_id):
    """Adopt AI-extracted issues as risks."""
    db.get_or_404(Project, project_id)
    data = request.get_json() or {}
    issues = data.get('issues', [])
    aar_id = data.get('aar_id')
    if not issues:
        return api_err(msg='无遗留问题')
    created = 0
    for item in issues:
        title = (item.get('title') or '').strip()
        if not title:
            continue
        # Dedup
        exists = Risk.query.filter_by(project_id=project_id, title=title, status='open').first()
        if exists:
            continue
        owner_name = (item.get('owner') or '').strip()
        try:
            due = date.fromisoformat(item.get('deadline', ''))
        except (ValueError, TypeError):
            due = date.today() + timedelta(days=7)
        severity = item.get('severity', 'medium')
        if severity not in ('high', 'medium', 'low'):
            severity = 'medium'
        risk = Risk(
            project_id=project_id, title=title, severity=severity,
            owner=owner_name or None, owner_id=_resolve_owner_id(owner_name),
            due_date=due, created_by=current_user.id,
            tracker_id=_resolve_owner_id(owner_name) or current_user.id,
            aar_id=int(aar_id) if aar_id else None,
        )
        db.session.add(risk)
        created += 1
    db.session.commit()
    return api_ok(created=created)
