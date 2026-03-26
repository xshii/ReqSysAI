"""Risk management routes for the project blueprint."""
from datetime import date, datetime, timedelta, timezone

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.project import Project
from app.models.risk import Risk
from app.models.user import User
from app.project import project_bp
from app.project.routes import _check_project_access, _resolve_owner_id

# ---- Risk management ----

@project_bp.route('/<int:project_id>/risks')
@login_required
def risk_list(project_id):
    project = db.get_or_404(Project, project_id)
    denied = _check_project_access(project)
    if denied:
        return denied
    status = request.args.get('status', '')
    severity = request.args.get('severity', '')
    overdue_filter = request.args.get('overdue', '')
    domain_filter = request.args.get('domain', '')

    query = Risk.query.filter_by(project_id=project_id).filter(Risk.deleted_at.is_(None))
    if status:
        query = query.filter_by(status=status)
    if overdue_filter:
        query = query.filter(Risk.status == 'open', Risk.due_date < date.today())
    if severity:
        query = query.filter_by(severity=severity)
    if domain_filter:
        if domain_filter == '未分类':
            query = query.filter(db.or_(Risk.owner_id.is_(None),
                                        ~Risk.owner_id.in_(db.session.query(User.id).filter(User.domain.isnot(None), User.domain != ''))))
        else:
            query = query.filter(Risk.owner_id.in_(db.session.query(User.id).filter_by(domain=domain_filter)))
    severity_order = db.case({'high': 0, 'medium': 1, 'low': 2}, value=Risk.severity)
    risks = query.order_by(severity_order, Risk.status, Risk.due_date).all()

    from app.models.requirement import Requirement
    reqs = Requirement.query.filter_by(project_id=project_id).order_by(Requirement.number).all()
    users = User.query.filter_by(is_active=True).order_by(User.name).all()

    # Stats for EML header
    all_risks = Risk.query.filter_by(project_id=project_id).filter(Risk.deleted_at.is_(None)).all()
    risk_stats = {
        'total': len(all_risks),
        'open': sum(1 for r in all_risks if r.status == 'open'),
        'overdue': sum(1 for r in all_risks if r.is_overdue),
        'high': sum(1 for r in all_risks if r.severity == 'high' and r.status == 'open'),
        'high_total': sum(1 for r in all_risks if r.severity == 'high'),
        'medium': sum(1 for r in all_risks if r.severity == 'medium' and r.status == 'open'),
        'medium_total': sum(1 for r in all_risks if r.severity == 'medium'),
        'low': sum(1 for r in all_risks if r.severity == 'low' and r.status == 'open'),
        'low_total': sum(1 for r in all_risks if r.severity == 'low'),
        'resolved': sum(1 for r in all_risks if r.status == 'resolved'),
        'closed': sum(1 for r in all_risks if r.status == 'closed'),
    }

    # Per-domain stats: {domain: {total, open}}
    from collections import defaultdict
    domain_stats = defaultdict(lambda: {'total': 0, 'open': 0})
    for r in all_risks:
        domain = (r.owner_user.domain if r.owner_user and r.owner_user.domain else '未分类')
        domain_stats[domain]['total'] += 1
        if r.status == 'open':
            domain_stats[domain]['open'] += 1
    # Sort: open desc, then total desc
    domain_stats = dict(sorted(domain_stats.items(), key=lambda x: (-x[1]['open'], -x[1]['total'])))

    from app.utils.recipients import compute_default_recipients
    risk_to, risk_cc = compute_default_recipients(project_id)
    is_pm = current_user.is_admin or project.owner_id == current_user.id
    return render_template('project/risks.html', project=project, risks=risks,
                           reqs=reqs, users=users, today=date.today(),
                           cur_status=status, cur_severity=severity, cur_overdue=overdue_filter,
                           risk_stats=risk_stats, domain_stats=domain_stats, cur_domain=domain_filter,
                           default_to=risk_to, default_cc=risk_cc, is_pm=is_pm)


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
        owner_id=_resolve_owner_id(request.form.get('owner', '').strip()),
        tracker_id=request.form.get('tracker_id', type=int) or None,
        requirement_id=request.form.get('requirement_id', type=int) or None,
        due_date=date.fromisoformat(request.form.get('due_date')) if request.form.get('due_date') else None,
        created_by=current_user.id,
        owner_since=datetime.now(timezone.utc) if request.form.get('owner', '').strip() else None,
    )
    db.session.add(risk)
    # Notify owner and tracker
    from app.services.notify import notify
    risk_link = url_for('project.risk_list', project_id=project_id)
    if risk.owner_id and risk.owner_id != current_user.id:
        notify(risk.owner_id, 'risk', f'你被指定为风险「{title}」的责任人', risk_link)
    if risk.tracker_id and risk.tracker_id != current_user.id and risk.tracker_id != risk.owner_id:
        notify(risk.tracker_id, 'risk', f'你被指定为风险「{title}」的跟踪人', risk_link)
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
        latest = risk.comments[0]  # ordered desc
        if (datetime.now(timezone.utc).replace(tzinfo=None) - latest.created_at).total_seconds() < 86400:
            resolution = latest.content
    if not resolution:
        flash('请填写解决方案（或先添加评论）', 'danger')
        return redirect(url_for('project.risk_list', project_id=risk.project_id))
    risk.status = 'resolved'
    risk.resolution = resolution
    risk.resolved_at = datetime.now(timezone.utc)
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
    """Soft delete a risk + audit log. Only PM/Admin."""
    from app.models.risk import RiskAuditLog
    risk = db.get_or_404(Risk, risk_id)
    project = db.session.get(Project, risk.project_id)
    if not (current_user.is_admin or (project and project.owner_id == current_user.id)):
        if request.is_json:
            return jsonify(ok=False, msg='仅 PM 或管理员可删除风险'), 403
        flash('仅 PM 或管理员可删除风险', 'danger')
        return redirect(url_for('project.risk_list', project_id=risk.project_id))
    risk.deleted_at = datetime.now(timezone.utc)
    risk.deleted_by = current_user.id
    db.session.add(RiskAuditLog(risk_id=risk.id, user_id=current_user.id, action='deleted', detail=risk.title))
    from app.services.audit import log_audit
    log_audit('soft_delete', 'risk', risk.id, risk.title)
    db.session.commit()
    if request.is_json:
        return jsonify(ok=True)
    flash('风险已删除', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/<int:project_id>/risks/export-csv')
@login_required
def risk_export_csv(project_id):
    """Export project risks as CSV."""
    import csv
    import io

    from flask import Response
    _ = db.get_or_404(Project, project_id)
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
    from urllib.parse import quote
    p = db.session.get(Project, project_id)
    fname = f"{p.name}_风险问题_{date.today().strftime('%Y%m%d')}.csv"
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(fname)}"})


@project_bp.route('/<int:project_id>/risks/import-csv', methods=['POST'])
@login_required
def risk_import_csv(project_id):
    """Import risks from CSV."""
    import csv
    import io
    _ = db.get_or_404(Project, project_id)
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
            owner_id=_resolve_owner_id((row.get('责任人') or '').strip()),
            tracker_id=user_map.get(tracker_name),
            due_date=due,
            description=(row.get('描述') or '').strip() or None,
            resolution=resolution_text,
            created_by=current_user.id,
        )
        if status_val == 'resolved' and resolution_text:
            risk.resolved_at = datetime.now(timezone.utc)
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
    from app.models.risk import RiskComment
    risk = db.get_or_404(Risk, risk_id)
    old_owner = risk.owner
    risk.title = request.form.get('title', risk.title).strip()
    risk.severity = request.form.get('severity', risk.severity)
    new_owner = request.form.get('owner', '').strip() or None
    risk.owner = new_owner
    risk.owner_id = _resolve_owner_id(risk.owner)
    tracker_id = request.form.get('tracker_id', type=int)
    risk.tracker_id = tracker_id if tracker_id else None
    due = request.form.get('due_date', '')
    if due:
        try:
            risk.due_date = datetime.strptime(due, '%Y-%m-%d').date()
        except ValueError:
            pass
    # Log owner change as comment with hold duration
    if new_owner != old_owner:
        now = datetime.now(timezone.utc)
        if old_owner and risk.owner_since:
            # 有前任且有接手时间，计算持有时长
            delta = now - risk.owner_since
            days = delta.days
            hours = delta.seconds // 3600
            duration = f'{days}天{hours}小时' if days else f'{hours}小时'
            msg = f'责任人由「{old_owner}」变更为「{new_owner or "无"}」（{old_owner}持有{duration}）'
        elif old_owner:
            # 有前任但无接手时间（历史数据）
            msg = f'责任人由「{old_owner}」变更为「{new_owner or "无"}」'
        else:
            # 从无人指派到有人
            msg = f'指派责任人「{new_owner}」'
        db.session.add(RiskComment(risk_id=risk.id, user_id=current_user.id, content=msg))
        risk.owner_since = now if new_owner else None
    db.session.commit()
    flash('风险已更新', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


@project_bp.route('/risks/<int:risk_id>/inline-edit', methods=['POST'])
@login_required
def risk_inline_edit(risk_id):
    """Quick inline update for severity or status."""
    risk = db.get_or_404(Risk, risk_id)
    data = request.get_json(silent=True) or {}
    field = data.get('field')
    value = data.get('value', '').strip()
    if field == 'severity' and value in ('high', 'medium', 'low'):
        risk.severity = value
    elif field == 'status' and value in ('open', 'resolved', 'closed'):
        if value == 'resolved' and risk.status == 'open':
            risk.resolved_at = datetime.now(timezone.utc)
        risk.status = value
    else:
        return jsonify(ok=False, msg='无效字段或值')
    db.session.commit()
    return jsonify(ok=True)


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


@project_bp.route('/risks/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def risk_comment_delete(comment_id):
    """Delete a risk comment. Anyone can delete, with audit trail."""
    from app.models.audit import AuditLog
    from app.models.risk import RiskComment
    comment = db.get_or_404(RiskComment, comment_id)
    risk = db.get_or_404(Risk, comment.risk_id)
    # Audit log before deletion
    db.session.add(AuditLog(
        user_id=current_user.id, action='delete', entity_type='risk_comment',
        entity_id=comment.id, entity_title=f'风险「{risk.title[:50]}」评论',
        detail=f'作者: {comment.user.name}, 内容: {comment.content[:200]}',
        ip_address=request.remote_addr,
    ))
    db.session.delete(comment)
    db.session.commit()
    flash('评论已删除', 'success')
    return redirect(url_for('project.risk_list', project_id=risk.project_id))


# ---- AI Risk Scan ----

@project_bp.route('/<int:project_id>/risks/ai-scan', methods=['POST'])
@login_required
def risk_ai_scan(project_id):
    """AI scans project data to identify potential risks."""
    from datetime import date, timedelta

    from sqlalchemy.orm import joinedload

    from app.models.requirement import Requirement
    from app.models.todo import Todo, todo_requirements
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt

    project = db.get_or_404(Project, project_id)
    reqs = Requirement.query.filter_by(project_id=project_id).order_by(Requirement.number).all()
    today = date.today()

    # Existing risks (to avoid duplicates)
    existing_risks = Risk.query.filter_by(project_id=project_id, status='open').all()

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
