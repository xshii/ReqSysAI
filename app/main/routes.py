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
     .order_by(Todo.sort_order).all()
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

    # Last month approved incentives
    from app.models.incentive import Incentive
    last_month_start = today.replace(day=1) - timedelta(days=1)
    last_month_start = last_month_start.replace(day=1)
    approved_incentives = Incentive.query.filter(
        Incentive.status == 'approved',
        Incentive.reviewed_at >= str(last_month_start),
    ).order_by(Incentive.reviewed_at.desc()).all()

    # Rant wall (graffiti board)
    from app.models.rant import Rant
    rants = Rant.query.order_by(Rant.created_at.desc()).limit(20).all()

    return render_template('main/index.html',
        my_todos=my_todos, todo_total=todo_total, todo_done=todo_done,
        my_reqs=my_reqs, my_risks=my_risks, today=today,
        approved_incentives=approved_incentives, rants=rants,
    )


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
