from datetime import date, timedelta

from flask import render_template, request, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.extensions import db
from app.models.requirement import Requirement
from app.models.todo import Todo


@main_bp.route('/')
@login_required
def index():
    today = date.today()

    # My today's todos
    my_todos = Todo.query.filter_by(user_id=current_user.id).filter(
        db.or_(
            Todo.status == 'todo',
            db.and_(Todo.status == 'done', Todo.done_date == today),
        )
    ).options(joinedload(Todo.items), joinedload(Todo.requirements))\
     .order_by(db.case((Todo.status == 'todo', 0), else_=1), Todo.sort_order).all()
    todo_total = len(my_todos)
    todo_done = sum(1 for t in my_todos if t.status == 'done')

    # My assigned requirements (active)
    my_reqs = Requirement.query.filter_by(assignee_id=current_user.id)\
        .filter(Requirement.status.notin_(['done', 'closed']))\
        .options(joinedload(Requirement.project))\
        .order_by(Requirement.updated_at.desc()).limit(10).all()

    # My related risks (tracker or created_by)
    from app.models.risk import Risk
    my_risks = Risk.query.filter(
        Risk.status == 'open',
        db.or_(Risk.tracker_id == current_user.id, Risk.created_by == current_user.id),
    ).order_by(Risk.due_date).all()

    # Alerts: overdue requirements + overdue risks
    overdue_reqs = [r for r in my_reqs if r.due_date and r.due_date < today and r.status not in ('done', 'closed')]
    overdue_risks = [r for r in my_risks if r.is_overdue]
    alerts = []
    for r in overdue_reqs:
        alerts.append(f'需求 [{r.number}] {r.title} 已超期 ({r.due_date.strftime("%m-%d")})')
    for r in overdue_risks:
        alerts.append(f'风险「{r.title}」已超期 ({r.due_date.strftime("%m-%d") if r.due_date else ""})')

    # Last month approved incentives
    from app.models.incentive import Incentive
    last_month_start = today.replace(day=1) - timedelta(days=1)
    last_month_start = last_month_start.replace(day=1)
    approved_incentives = Incentive.query.filter(
        Incentive.status == 'approved',
        Incentive.reviewed_at >= str(last_month_start),
    ).order_by(Incentive.reviewed_at.desc()).all()

    # AI usage ranking: top5 by call count & estimated tokens
    from app.models.ai_log import AIParseLog
    ai_stats = db.session.query(
        AIParseLog.created_by,
        db.func.count(AIParseLog.id).label('call_count'),
        db.func.sum(db.func.length(AIParseLog.raw_input)).label('input_chars'),
        db.func.sum(db.func.length(AIParseLog.ai_output)).label('output_chars'),
    ).group_by(AIParseLog.created_by)\
     .order_by(db.func.count(AIParseLog.id).desc())\
     .limit(5).all()

    from app.models.user import User
    ai_ranking = []
    for row in ai_stats:
        user = db.session.get(User, row.created_by)
        input_chars = row.input_chars or 0
        output_chars = row.output_chars or 0
        # Rough token estimate: 1 Chinese char ≈ 1.5 tokens, mixed avg ≈ 0.6 tokens/char
        est_tokens = int((input_chars + output_chars) * 0.6)
        ai_ranking.append({
            'name': user.name if user else '未知',
            'calls': row.call_count,
            'tokens': est_tokens,
        })

    # Graffiti board: top3 all-time + current month
    from app.models.rant import Rant
    month_start = today.replace(day=1)
    top_rants = Rant.query.filter(Rant.likes > 0).order_by(Rant.likes.desc()).limit(3).all()
    top_ids = {r.id for r in top_rants}
    month_q = Rant.query.filter(Rant.created_at >= str(month_start))
    if top_ids:
        month_q = month_q.filter(~Rant.id.in_(top_ids))
    month_rants = month_q.order_by(Rant.created_at.desc()).limit(20).all()
    rants = top_rants + month_rants

    return render_template('main/index.html',
        my_todos=my_todos, todo_total=todo_total, todo_done=todo_done,
        my_reqs=my_reqs, my_risks=my_risks, today=today,
        approved_incentives=approved_incentives, rants=rants,
        ai_ranking=ai_ranking, alerts=alerts,
    )


@main_bp.route('/todo/<int:todo_id>/toggle', methods=['POST'])
@login_required
def toggle_todo(todo_id):
    """Toggle todo done/undone from homepage."""
    todo = db.session.get(Todo, todo_id)
    if not todo or todo.user_id != current_user.id:
        return redirect(url_for('main.index'))
    if todo.status == 'done':
        todo.status = 'todo'
        todo.done_date = None
        for item in todo.items:
            item.is_done = False
    else:
        todo.status = 'done'
        todo.done_date = date.today()
        for item in todo.items:
            item.is_done = True
    db.session.commit()
    return redirect(url_for('main.index'))


@main_bp.route('/rant', methods=['POST'])
@login_required
def post_rant():
    from app.models.rant import Rant
    content = request.form.get('content', '').strip()[:500]
    alias = request.form.get('alias', '').strip()[:30] or None
    if content:
        db.session.add(Rant(content=content, alias=alias))
        db.session.commit()
    return redirect(url_for('main.index'))


@main_bp.route('/rant/<int:rant_id>/like', methods=['POST'])
@login_required
def like_rant(rant_id):
    from app.models.rant import Rant
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
    from app.models.rant import Rant
    rant = db.session.get(Rant, rant_id)
    if rant:
        db.session.delete(rant)
        db.session.commit()
    return redirect(url_for('main.index'))
