from datetime import date, timedelta

from flask import render_template, request, redirect, url_for, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.extensions import db
from app.constants import (
    TODO_STATUS_TODO, TODO_STATUS_DONE, REQ_INACTIVE_STATUSES,
    HEATMAP_DAYS, AI_TOKEN_RATIO, MAX_RECENT_REQS_FOR_QUICK_TODO,
    MAX_RANT_LENGTH,
)
from app.models.requirement import Requirement
from app.models.todo import Todo, TodoItem
from app.models.risk import Risk
from app.models.incentive import Incentive
from app.models.ai_log import AIParseLog
from app.models.user import User
from app.models.rant import Rant


def _prev_workday(today):
    """Return previous workday (Friday if today is Monday)."""
    if today.weekday() == 0:
        return today - timedelta(days=3)
    return today - timedelta(days=1)


def _yesterday_reqs(user_id, yesterday):
    """Get active requirements linked to yesterday's todos."""
    todos = Todo.query.filter_by(user_id=user_id).filter(
        db.or_(
            db.and_(Todo.status == TODO_STATUS_DONE, Todo.done_date == yesterday),
            db.and_(Todo.status == TODO_STATUS_TODO, Todo.created_date <= yesterday),
        )
    ).options(joinedload(Todo.requirements)).all()
    reqs, seen = [], set()
    for t in todos:
        for r in t.requirements:
            if r.id not in seen and r.status not in REQ_INACTIVE_STATUSES:
                reqs.append(r)
                seen.add(r.id)
    return reqs


@main_bp.route('/')
@login_required
def index():
    today = date.today()

    # My today's todos
    my_todos = Todo.query.filter_by(user_id=current_user.id).filter(
        db.or_(
            Todo.status == TODO_STATUS_TODO,
            db.and_(Todo.status == TODO_STATUS_DONE, Todo.done_date == today),
        )
    ).options(joinedload(Todo.items), joinedload(Todo.requirements))\
     .order_by(db.case((Todo.status == TODO_STATUS_TODO, 0), else_=1), Todo.sort_order).all()
    todo_total = len(my_todos)
    todo_done = sum(1 for t in my_todos if t.status == TODO_STATUS_DONE)

    # My assigned requirements (active)
    my_reqs = Requirement.query.filter_by(assignee_id=current_user.id)\
        .filter(Requirement.status.notin_(REQ_INACTIVE_STATUSES))\
        .options(joinedload(Requirement.project))\
        .order_by(Requirement.updated_at.desc()).limit(10).all()

    # Yesterday's linked requirements for quick-todo hint
    yesterday = _prev_workday(today)
    recent_reqs = _yesterday_reqs(current_user.id, yesterday)
    recent_req_hint = '、'.join(r.number for r in recent_reqs[:MAX_RECENT_REQS_FOR_QUICK_TODO])

    # My related risks
    my_risks = Risk.query.filter(
        Risk.status == 'open',
        db.or_(Risk.tracker_id == current_user.id, Risk.created_by == current_user.id),
    ).order_by(Risk.due_date).all()

    # Alerts: overdue requirements + overdue risks
    alerts = [
        f'需求 [{r.number}] {r.title} 已超期 ({r.due_date.strftime("%m-%d")})'
        for r in my_reqs if r.due_date and r.due_date < today
    ] + [
        f'风险「{r.title}」已超期 ({r.due_date.strftime("%m-%d") if r.due_date else ""})'
        for r in my_risks if r.is_overdue
    ]

    # Last month approved incentives
    last_month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    approved_incentives = Incentive.query.filter(
        Incentive.status == 'approved',
        Incentive.reviewed_at >= str(last_month_start),
    ).order_by(Incentive.reviewed_at.desc()).all()

    # AI usage ranking: top5
    ai_stats = db.session.query(
        AIParseLog.created_by,
        db.func.count(AIParseLog.id).label('call_count'),
        db.func.sum(db.func.length(AIParseLog.raw_input)).label('input_chars'),
        db.func.sum(db.func.length(AIParseLog.ai_output)).label('output_chars'),
    ).group_by(AIParseLog.created_by)\
     .order_by(db.func.count(AIParseLog.id).desc()).limit(5).all()

    ai_ranking = []
    for row in ai_stats:
        user = db.session.get(User, row.created_by)
        chars = (row.input_chars or 0) + (row.output_chars or 0)
        ai_ranking.append({
            'name': user.name if user else '未知',
            'calls': row.call_count,
            'tokens': int(chars * AI_TOKEN_RATIO),
        })

    # Contribution heatmap
    heatmap_start = today - timedelta(days=HEATMAP_DAYS)
    heatmap_rows = db.session.query(
        Todo.done_date, db.func.count(Todo.id),
    ).filter(
        Todo.user_id == current_user.id,
        Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= heatmap_start,
    ).group_by(Todo.done_date).all()
    heatmap = {str(row[0]): row[1] for row in heatmap_rows}

    # Graffiti board: top3 all-time + current month
    month_start = today.replace(day=1)
    top_rants = Rant.query.filter(Rant.likes > 0).order_by(Rant.likes.desc()).limit(3).all()
    top_ids = {r.id for r in top_rants}
    month_q = Rant.query.filter(Rant.created_at >= str(month_start))
    if top_ids:
        month_q = month_q.filter(~Rant.id.in_(top_ids))
    rants = top_rants + month_q.order_by(Rant.created_at.desc()).limit(20).all()

    return render_template('main/index.html',
        my_todos=my_todos, todo_total=todo_total, todo_done=todo_done,
        my_reqs=my_reqs, my_risks=my_risks, today=today,
        approved_incentives=approved_incentives, rants=rants,
        ai_ranking=ai_ranking, alerts=alerts,
        recent_req_hint=recent_req_hint,
        heatmap=heatmap, heatmap_start=heatmap_start, timedelta=timedelta,
    )


@main_bp.route('/quick-todo', methods=['POST'])
@login_required
def quick_todo():
    """Create todo from homepage. If req_id given, link to that requirement."""
    title = request.form.get('title', '').strip()
    if not title:
        return redirect(url_for('main.index'))

    today = date.today()
    req_id = request.form.get('req_id', type=int)
    reqs = []
    if req_id:
        req = db.session.get(Requirement, req_id)
        if req:
            reqs = [req]
    todo = Todo(
        user_id=current_user.id,
        title=title,
        due_date=today,
        requirements=reqs,
    )
    todo.items.append(TodoItem(title=title, sort_order=0))
    db.session.add(todo)
    db.session.commit()
    return redirect(url_for('main.index'))


@main_bp.route('/api/search')
@login_required
def api_search():
    """Global search API for Cmd+K modal."""
    from app.services.search import search
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify(ok=True, results=[])
    results = search(q)
    # Add URLs for each result
    url_map = {
        'requirement': lambda r: url_for('requirement.requirement_detail', req_id=int(r['id'])),
        'todo': lambda r: url_for('todo.team'),
        'project': lambda r: url_for('project.project_detail', project_id=int(r['id'])),
        'user': lambda r: url_for('admin.user_list'),
    }
    type_labels = {'requirement': '需求', 'todo': 'Todo', 'project': '项目', 'user': '用户'}
    for r in results:
        fn = url_map.get(r['type'])
        r['url'] = fn(r) if fn else '#'
        r['type_label'] = type_labels.get(r['type'], r['type'])
    return jsonify(ok=True, results=results)


@main_bp.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def toggle_todo(todo_id):
    """Toggle todo done/undone from homepage."""
    todo = db.session.get(Todo, todo_id)
    if not todo or todo.user_id != current_user.id:
        return redirect(url_for('main.index'))
    if todo.status == TODO_STATUS_DONE:
        todo.status = TODO_STATUS_TODO
        todo.done_date = None
        for item in todo.items:
            item.is_done = False
    else:
        todo.status = TODO_STATUS_DONE
        todo.done_date = date.today()
        for item in todo.items:
            item.is_done = True
    db.session.commit()
    return redirect(url_for('main.index'))


@main_bp.route('/rant', methods=['POST'])
@login_required
def post_rant():
    content = request.form.get('content', '').strip()[:MAX_RANT_LENGTH]
    alias = request.form.get('alias', '').strip()[:30] or None
    if content:
        db.session.add(Rant(content=content, alias=alias))
        db.session.commit()
    return redirect(url_for('main.index'))


@main_bp.route('/rant/<int:rant_id>/like', methods=['POST'])
@login_required
def like_rant(rant_id):
    rant = db.session.get(Rant, rant_id)
    if rant:
        rant.likes = (rant.likes or 0) + 1
        db.session.commit()
    return redirect(url_for('main.index'))


@main_bp.route('/rant/<int:rant_id>/delete', methods=['POST'])
@login_required
def delete_rant(rant_id):
    if not current_user.is_admin:
        return redirect(url_for('main.index'))
    rant = db.session.get(Rant, rant_id)
    if rant:
        db.session.delete(rant)
        db.session.commit()
    return redirect(url_for('main.index'))
