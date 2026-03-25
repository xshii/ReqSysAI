"""Notification service — create notifications for users."""
from app.extensions import db
from app.models.notification import Notification


def notify(user_id, type_, title, link=None):
    """Create a notification for a user."""
    if not user_id:
        return
    db.session.add(Notification(user_id=user_id, type=type_, title=title, link=link))


def notify_many(user_ids, type_, title, link=None):
    """Create notifications for multiple users."""
    for uid in set(user_ids):
        if uid:
            db.session.add(Notification(user_id=uid, type=type_, title=title, link=link))
