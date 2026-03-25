"""Global search — direct LIKE queries, no index needed."""

from app.extensions import db
from app.models.meeting import Meeting
from app.models.project import Project
from app.models.requirement import Requirement
from app.models.risk import Risk
from app.models.todo import Todo
from app.models.user import User


def search(query, limit=20, current_user_id=None):
    """Search across all entities using LIKE. Returns list of dicts."""
    if not query or not query.strip():
        return []
    q = f'%{query.strip()}%'
    results = []

    # Requirements
    for r in Requirement.query.filter(
        db.or_(Requirement.title.like(q), Requirement.number.like(q), Requirement.description.like(q))
    ).limit(limit).all():
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
    for p in Project.query.filter(
        db.or_(Project.name.like(q), Project.description.like(q))
    ).limit(limit).all():
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
    for m in Meeting.query.filter(
        db.or_(Meeting.title.like(q), Meeting.content.like(q), Meeting.attendees.like(q))
    ).order_by(Meeting.date.desc()).limit(limit).all():
        results.append({'type': 'meeting', 'id': m.id, 'project_id': m.project_id,
                        'title': m.title, 'extra': m.date.strftime('%Y-%m-%d') if m.date else ''})

    # Risks
    for r in Risk.query.filter(
        Risk.deleted_at.is_(None),
        db.or_(Risk.title.like(q), Risk.description.like(q), Risk.owner.like(q))
    ).limit(limit).all():
        results.append({'type': 'risk', 'id': r.id, 'project_id': r.project_id,
                        'title': r.title, 'extra': r.status})

    # AAR
    from app.models.knowledge import AAR
    for a in AAR.query.filter(
        db.or_(AAR.title.like(q), AAR.goal.like(q), AAR.result.like(q),
               AAR.analysis.like(q), AAR.action.like(q))
    ).order_by(AAR.date.desc()).limit(limit).all():
        results.append({'type': 'aar', 'id': a.id, 'project_id': a.project_id,
                        'title': a.title, 'extra': a.date.strftime('%Y-%m-%d') if a.date else ''})

    return results[:limit]
