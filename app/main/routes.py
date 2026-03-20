from flask import render_template
from flask_login import login_required, current_user

from app.main import main_bp
from app.models.project import Project
from app.models.requirement import Requirement


@main_bp.route('/')
@login_required
def index():
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
        my_reqs=my_reqs, active_projects=active_projects,
        total_reqs=total_reqs, done_reqs=done_reqs,
        my_total=my_total, my_done=my_done,
    )
