"""Lightweight domain event system using blinker signals."""

from blinker import Namespace

_signals = Namespace()

requirement_status_changed = _signals.signal('requirement-status-changed')
todo_completed = _signals.signal('todo-completed')
risk_escalated = _signals.signal('risk-escalated')
requirement_assigned = _signals.signal('requirement-assigned')


def fire(signal, **kwargs):
    """Send a signal with keyword data."""
    signal.send(None, **kwargs)
