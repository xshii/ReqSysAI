"""Audit log service."""
from flask import request as flask_request
from flask_login import current_user

from app.extensions import db
from app.models.audit import AuditLog


def log_audit(action, entity_type, entity_id=None, entity_title=None, detail=None):
    """Record an audit log entry."""
    try:
        uid = current_user.id if current_user.is_authenticated else None
    except Exception:
        uid = None
    ip = None
    try:
        ip = flask_request.remote_addr
    except Exception:  # noqa: S110
        pass
    db.session.add(AuditLog(
        user_id=uid, action=action, entity_type=entity_type,
        entity_id=entity_id, entity_title=entity_title,
        detail=detail, ip_address=ip,
    ))
