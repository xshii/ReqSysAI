from datetime import datetime

from app.extensions import db


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(30), nullable=False)  # risk/todo_help/permission/meeting/aar
    title = db.Column(db.String(300), nullable=False)
    link = db.Column(db.String(500), nullable=True)  # URL to navigate to
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now())

    user = db.relationship('User', backref='notifications')

    TYPE_LABELS = {
        'risk': '风险',
        'todo_help': '求助',
        'permission': '权限',
        'meeting': '会议',
        'aar': 'AAR',
        'gift': '激励礼物',
        'request': '外部诉求',
    }

    TYPE_ICONS = {
        'risk': 'exclamation-triangle',
        'todo_help': 'people',
        'permission': 'key',
        'meeting': 'camera-video',
        'aar': 'journal-text',
        'gift': 'gift',
        'request': 'megaphone',
    }

    @property
    def type_label(self):
        return self.TYPE_LABELS.get(self.type, self.type)

    @property
    def type_icon(self):
        return self.TYPE_ICONS.get(self.type, 'bell')
