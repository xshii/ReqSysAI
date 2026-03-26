"""Global search — direct LIKE queries, no index needed."""

from app.extensions import db
from app.models.meeting import Meeting
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.risk import Risk
from app.models.todo import Todo
from app.models.user import User


def search(query, limit=20, current_user_id=None, is_manager=False):
    """Search across all entities using LIKE. Returns list of dicts."""
    if not query or not query.strip():
        return []
    q = f'%{query.strip()}%'
    results = []

    # Hidden project IDs (for non-managers)
    hidden_pids = set()
    if not is_manager:
        hidden_pids = {p.id for p in Project.query.filter_by(is_hidden=True).all()}

    # Requirements
    req_q = Requirement.query.filter(
        db.or_(Requirement.title.like(q), Requirement.number.like(q), Requirement.description.like(q))
    )
    if hidden_pids:
        req_q = req_q.filter(Requirement.project_id.notin_(hidden_pids))
    for r in req_q.limit(limit).all():
        results.append({'type': 'requirement', 'id': r.id,
                        'title': f'[{r.number}] {r.title}', 'extra': r.status})

    # Todos (recent, only current user's todos)
    todo_q = Todo.query.filter(Todo.title.like(q))
    if current_user_id:
        todo_q = todo_q.filter(Todo.user_id == current_user_id)
    for t in todo_q.order_by(Todo.id.desc()).limit(limit).all():
        results.append({'type': 'todo', 'id': t.id,
                        'title': t.title, 'extra': t.status})

    # Projects
    proj_q = Project.query.filter(
        db.or_(Project.name.like(q), Project.description.like(q))
    )
    if hidden_pids:
        proj_q = proj_q.filter(Project.id.notin_(hidden_pids))
    for p in proj_q.limit(limit).all():
        results.append({'type': 'project', 'id': p.id,
                        'title': p.name, 'extra': ''})

    # Users
    for u in User.query.filter(
        User.is_active == True,
        db.or_(User.name.like(q), User.pinyin.like(q), User.employee_id.like(q))
    ).limit(limit).all():
        results.append({'type': 'user', 'id': u.id,
                        'title': u.name, 'extra': u.employee_id or ''})

    # Meetings
    meet_q = Meeting.query.filter(
        db.or_(Meeting.title.like(q), Meeting.content.like(q), Meeting.attendees.like(q))
    )
    if hidden_pids:
        meet_q = meet_q.filter(Meeting.project_id.notin_(hidden_pids))
    for m in meet_q.order_by(Meeting.date.desc()).limit(limit).all():
        results.append({'type': 'meeting', 'id': m.id, 'project_id': m.project_id,
                        'title': m.title, 'extra': m.date.strftime('%Y-%m-%d') if m.date else ''})

    # Risks
    risk_q = Risk.query.filter(
        Risk.deleted_at.is_(None),
        db.or_(Risk.title.like(q), Risk.description.like(q), Risk.owner.like(q))
    )
    if hidden_pids:
        risk_q = risk_q.filter(Risk.project_id.notin_(hidden_pids))
    for r in risk_q.limit(limit).all():
        results.append({'type': 'risk', 'id': r.id, 'project_id': r.project_id,
                        'title': r.title, 'extra': r.status})

    # AAR
    from app.models.knowledge import AAR
    aar_q = AAR.query.filter(
        db.or_(AAR.title.like(q), AAR.goal.like(q), AAR.result.like(q),
               AAR.analysis.like(q), AAR.action.like(q))
    )
    if hidden_pids:
        aar_q = aar_q.filter(AAR.project_id.notin_(hidden_pids))
    for a in aar_q.order_by(AAR.date.desc()).limit(limit).all():
        results.append({'type': 'aar', 'id': a.id, 'project_id': a.project_id,
                        'title': a.title, 'extra': a.date.strftime('%Y-%m-%d') if a.date else ''})

    return results[:limit]
