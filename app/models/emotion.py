from datetime import datetime, date

from app.extensions import db


class EmotionRecord(db.Model):
    """Saved emotion prediction result per member."""
    __tablename__ = 'emotion_records'

    id = db.Column(db.Integer, primary_key=True)
    scan_date = db.Column(db.Date, nullable=False)
    member_name = db.Column(db.String(100), nullable=False)
    group = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), nullable=False)  # 正常/疲劳/低迷/预警
    risk_level = db.Column(db.String(10), nullable=False)  # low/medium/high
    signals = db.Column(db.Text, nullable=True)  # JSON array
    suggestion = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by])
    comments = db.relationship('EmotionComment', backref='record', cascade='all, delete-orphan',
                               order_by='EmotionComment.created_at')

    @property
    def days_ago(self):
        return (date.today() - self.scan_date).days

    @property
    def signals_list(self):
        if not self.signals:
            return []
        import json
        try:
            return json.loads(self.signals)
        except (json.JSONDecodeError, TypeError):
            return []


class EmotionComment(db.Model):
    """Comment or follow-up on emotion record."""
    __tablename__ = 'emotion_comments'

    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, db.ForeignKey('emotion_records.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', lazy='joined')
