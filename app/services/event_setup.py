"""Wire event handlers to signals. Called once during app creation."""

from app.services.event_handlers import (
    on_requirement_status_changed,
    on_risk_escalated,
    on_todo_completed,
)
from app.services.events import (
    requirement_status_changed,
    risk_escalated,
    todo_completed,
)


def register_events():
    todo_completed.connect(on_todo_completed)
    requirement_status_changed.connect(on_requirement_status_changed)
    risk_escalated.connect(on_risk_escalated)
