from datetime import date

from flask import render_template
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.main import main_bp
from app.extensions import db
from app.models.project import Project
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
    ).options(joinedload(Todo.items)).order_by(Todo.sort_order).all()

    todo_total = len(my_todos)
    todo_done = sum(1 for t in my_todos if t.status == 'done')

    # My assigned requirements
    my_reqs = Requirement.query.filter_by(assignee_id=current_user.id)\
        .filter(Requirement.status.notin_(['done', 'closed']))\
        .order_by(Requirement.updated_at.desc()).limit(10).all()

    # Active projects
    active_projects = Project.query.filter_by(status='active')\
        .order_by(Project.updated_at.desc()).limit(5).all()

    # Stats
    total_reqs = Requirement.query.count()
    done_reqs = Requirement.query.filter(Requirement.status.in_(['done', 'closed'])).count()
    my_total = Requirement.query.filter_by(assignee_id=current_user.id).count()
    my_done = Requirement.query.filter_by(assignee_id=current_user.id)\
        .filter(Requirement.status.in_(['done', 'closed'])).count()

    return render_template('main/index.html',
        my_todos=my_todos, todo_total=todo_total, todo_done=todo_done,
        my_reqs=my_reqs, active_projects=active_projects,
        total_reqs=total_reqs, done_reqs=done_reqs,
        my_total=my_total, my_done=my_done, today=today,
    )
