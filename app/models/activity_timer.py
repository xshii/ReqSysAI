"""Quick activity timer records (meeting/review/break/other)."""
from app.extensions import db, _local_now


class ActivityTimer(db.Model):
    __tablename__ = 'activity_timers'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    activity = db.Column(db.String(30), nullable=False)  # meeting/review/break/other
    label = db.Column(db.String(50), nullable=False)      # 开会/评审/休息/其他
    started_at = db.Column(db.DateTime, nullable=False)
    minutes = db.Column(db.Integer, nullable=False, default=0)
    date = db.Column(db.Date, nullable=False)              # for grouping by day
    created_at = db.Column(db.DateTime, default=_local_now)

    user = db.relationship('User', backref='activity_timers')
