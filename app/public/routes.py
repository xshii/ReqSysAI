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
    from datetime import date, timedelta
    week_ago = date.today() - timedelta(days=7)
    # 进行中的（pending/accepted）始终显示
    active = ExternalRequest.query.filter_by(target_user_id=user.id)\
        .filter(ExternalRequest.status.in_(('pending', 'accepted')))\
        .order_by(ExternalRequest.created_at.desc()).all()
    # 近一周完成/婉拒的（默认展开）
    recent_done = ExternalRequest.query.filter_by(target_user_id=user.id)\
        .filter(ExternalRequest.status.in_(('done', 'rejected')),
                ExternalRequest.updated_at >= week_ago)\
        .order_by(ExternalRequest.created_at.desc()).all()
    # 更早的已完成/婉拒（折叠，分页）
    older_q = ExternalRequest.query.filter_by(target_user_id=user.id)\
        .filter(ExternalRequest.status.in_(('done', 'rejected')),
                db.or_(ExternalRequest.updated_at < week_ago, ExternalRequest.updated_at.is_(None)))\
        .order_by(ExternalRequest.created_at.desc())
    older_pagination = older_q.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('public/request_page.html', target_user=user,
                           active_requests=active, recent_done=recent_done,
                           older_pagination=older_pagination)


@public_bp.route('/helpdesk/<eid>/submit', methods=['POST'])
def request_submit(eid):
    """提交外部诉求。"""
    user = _get_user_by_eid(eid)
    title = request.form.get('title', '').strip()
    if not title:
        flash('请填写诉求标题', 'danger')
        return redirect(url_for('public.request_page', eid=eid))
    submitter = request.form.get('name', '').strip() or '匿名'
    urgency = request.form.get('urgency', 'week')
    if urgency not in ('today', 'tomorrow', 'week'):
        urgency = 'week'
    req = ExternalRequest(
        target_user_id=user.id,
        name=submitter,
        contact=request.form.get('contact', '').strip() or None,
        title=title,
        description=request.form.get('description', '').strip() or None,
        urgency=urgency,
    )
    db.session.add(req)

    # 创建求助 todo（类似 @人求助）
    from datetime import date, timedelta
    from app.models.todo import Todo, TodoItem
    urgency_days = {'today': 0, 'tomorrow': 1, 'week': 7}
    due = date.today() + timedelta(days=urgency_days.get(urgency, 7))
    urgency_label = ExternalRequest.URGENCY_MAP.get(urgency, ('一周内', 'info'))[0]
    todo_title = f'[外部诉求] {submitter}：{title}（{urgency_label}）'
    todo = Todo(user_id=user.id, title=todo_title, due_date=due,
                category='work', source='help')
    todo.items.append(TodoItem(title=todo_title, sort_order=0))
    db.session.add(todo)

    # 通知目标用户
    from app.services.notify import notify
    notify(user.id, 'request', f'收到外部诉求「{title}」— {submitter}',
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
