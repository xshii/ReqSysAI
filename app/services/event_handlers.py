"""Event subscribers — auto-transitions, logging, escalation."""

from datetime import date

from app.constants import REQ_INACTIVE_STATUSES, TODO_STATUS_DONE
from app.extensions import db


def on_todo_completed(sender, todo=None, **_):
    """When a todo completes, check if all todos for linked requirements are done.
    If so, auto-advance requirement status."""
    if not todo:
        return
    for req in todo.requirements:
        if req.status in REQ_INACTIVE_STATUSES:
            continue
        # Check all linked todos for this requirement
        from app.models.todo import Todo, todo_requirements
        pending = db.session.query(Todo.id).join(
            todo_requirements, Todo.id == todo_requirements.c.todo_id
        ).filter(
            todo_requirements.c.requirement_id == req.id,
            Todo.status != TODO_STATUS_DONE,
        ).count()
        if pending == 0:
            _auto_advance_requirement(req, reason='所有关联 Todo 已完成')


def on_requirement_status_changed(sender, requirement=None, old_status=None, new_status=None, **_):
    """When a child requirement completes, check if all siblings are done.
    If so, auto-advance parent."""
    if not requirement or not requirement.parent_id:
        return
    parent = requirement.parent
    if not parent or parent.status in REQ_INACTIVE_STATUSES:
        return
    # Check all children
    pending = sum(1 for c in parent.children if c.status not in REQ_INACTIVE_STATUSES)
    if pending == 0:
        _auto_advance_requirement(parent, reason='所有子需求已完成')


def on_risk_escalated(sender, risk=None, **_):
    """If risk is overdue and severity is not high, upgrade it."""
    if not risk or risk.status != 'open':
        return
    if risk.due_date and risk.due_date < date.today() and risk.severity != 'high':
        risk.severity = 'high'
        db.session.commit()


def _auto_advance_requirement(req, reason=''):
    """Advance requirement to next logical status."""
    from app.models.requirement import Activity
    transitions = req.allowed_next_statuses
    # Prefer advancing forward: in_test > done
    target = None
    for candidate in ('in_test', 'done'):
        if candidate in transitions:
            target = candidate
            break
    if not target and transitions:
        target = transitions[0]
    if target:
        old_label = req.status_label
        req.status = target
        db.session.add(Activity(
            requirement_id=req.id, user_id=req.assignee_id or req.created_by,
            action='status_changed',
            detail=f'{old_label} → {req.status_label}（自动：{reason}）',
        ))
        db.session.commit()
