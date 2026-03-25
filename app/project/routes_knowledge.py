"""Knowledge management and AAR routes for the project blueprint."""
from datetime import date, timedelta

from flask import current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.knowledge import AAR, Knowledge
from app.models.project import Project
from app.models.risk import Risk
from app.project import project_bp
from app.project.routes import _resolve_owner_id

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
    aars = AAR.query.filter_by(project_id=project_id).order_by(AAR.date.desc()).all()
    milestones = project.milestones
    return render_template('project/knowledge.html', project=project, items=items, aars=aars,
                           trigger_labels=AAR.TRIGGER_LABELS, ai_enabled=current_app.config.get('AI_ENABLED'),
                           link_types=Knowledge.LINK_TYPES,
                           existing_biz_cats=existing_biz_cats,
                           milestones=milestones, today=date.today())


# ---- AAR (After Action Review) ----

@project_bp.route('/<int:project_id>/aar', methods=['GET', 'POST'])
@login_required
def aar_list(project_id):
    project = db.get_or_404(Project, project_id)

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
        return jsonify(ok=False, msg='请先填写目标/结果/差异分析')

    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt
    action_line = f'改进措施：{action}' if action else ''
    tpl = get_prompt('aar_extract_issues')
    prompt = tpl.format(goal=goal or '未填写', result=result or '未填写',
                        analysis=analysis or '未填写', action_line=action_line)

    result_data, _ = call_ollama(prompt)
    # AI may return {"issues":[...]} or just [...]
    if isinstance(result_data, dict) and 'issues' in result_data:
        return jsonify(ok=True, issues=result_data['issues'])
    if isinstance(result_data, list):
        return jsonify(ok=True, issues=result_data)
    return jsonify(ok=False, msg='AI 提取失败')


@project_bp.route('/<int:project_id>/aar/adopt-risks', methods=['POST'])
@login_required
def aar_adopt_risks(project_id):
    """Adopt AI-extracted issues as risks."""
    db.get_or_404(Project, project_id)
    data = request.get_json() or {}
    issues = data.get('issues', [])
    if not issues:
        return jsonify(ok=False, msg='无遗留问题')
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
        )
        db.session.add(risk)
        created += 1
    db.session.commit()
    return jsonify(ok=True, created=created)
