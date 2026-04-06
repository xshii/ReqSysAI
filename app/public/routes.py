"""Public routes — no login required."""
from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.external_request import ExternalRequest
from app.models.user import User
from app.public import public_bp


def _get_user_by_eid(eid):
    """通过工号查找用户。"""
    return User.query.filter_by(employee_id=eid, is_active=True).first_or_404()


@public_bp.route('/helpdesk/<eid>')
def request_page(eid):
    """外部诉求页——公开，无需登录。显示提交表单 + 历史诉求（分页）。"""
    user = _get_user_by_eid(eid)
    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = ExternalRequest.query.filter_by(target_user_id=user.id)\
        .order_by(ExternalRequest.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
    return render_template('public/request_page.html', target_user=user, pagination=pagination)


@public_bp.route('/helpdesk/<eid>/submit', methods=['POST'])
def request_submit(eid):
    """提交外部诉求。"""
    user = _get_user_by_eid(eid)
    title = request.form.get('title', '').strip() or '其他'
    description = request.form.get('description', '').strip()
    if not description:
        flash('请填写详细描述', 'danger')
        return redirect(url_for('public.request_page', eid=eid))
    submitter = request.form.get('name', '').strip() or '匿名'
    # Parse deadline datetime
    from datetime import date, timedelta
    from datetime import datetime as _dt
    deadline_str = request.form.get('deadline', '').strip()
    try:
        deadline = _dt.strptime(deadline_str, '%Y-%m-%dT%H:%M') if deadline_str else None
    except ValueError:
        deadline = None
    if not deadline:
        deadline = _dt.combine(date.today() + timedelta(days=7), _dt.min.time().replace(hour=18))
    due = deadline.date()
    # Map to urgency for model compat
    days_left = (due - date.today()).days
    urgency = 'today' if days_left <= 0 else ('tomorrow' if days_left <= 1 else 'week')
    deadline_label = deadline.strftime('%m-%d %H:%M')

    # 用客户端本地时间作为 created_at
    client_time_str = request.form.get('client_time', '').strip()
    try:
        client_time = _dt.strptime(client_time_str, '%Y-%m-%dT%H:%M:%S') if client_time_str else None
    except ValueError:
        client_time = None

    req = ExternalRequest(
        target_user_id=user.id,
        name=submitter,
        title=title,
        description=description,
        urgency=urgency,
        status='pending',
    )
    if client_time:
        req.created_at = client_time
    db.session.add(req)

    # 创建求助 todo
    from app.models.todo import Todo, TodoItem
    todo_title = f'[外部诉求] {submitter}：{title} - {description}（{deadline_label}）'
    todo = Todo(user_id=user.id, title=todo_title, due_date=due,
                category='work', source='help')
    todo.items.append(TodoItem(title=todo_title, sort_order=0))
    db.session.flush()  # get req.id
    todo.blocked_reason = f'ext_req:{req.id}'
    db.session.add(todo)

    # 通知目标用户
    from app.services.notify import notify
    notify(user.id, 'request', f'收到外部诉求「{title}」— {submitter}，期望 {deadline_label} 前完成',
           url_for('public.request_page', eid=eid))
    db.session.commit()
    flash('诉求已提交，可随时回到此页面查看进展', 'success')
    return redirect(url_for('public.request_page', eid=eid))


@public_bp.route('/open/requests/<int:req_id>/respond', methods=['POST'])
@login_required
def request_respond(req_id):
    """内部人员回复/更新状态。"""
    er = db.get_or_404(ExternalRequest, req_id)
    status = request.form.get('status', er.status)
    response = request.form.get('response', '').strip()
    if status in ('pending', 'accepted', 'done', 'rejected'):
        er.status = status
    if response:
        er.response = response
    if not er.assigned_id:
        er.assigned_id = current_user.id
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(ok=True, status=er.status, status_label=er.status_label, status_color=er.status_color)
    return redirect(request.referrer or url_for('main.index'))
