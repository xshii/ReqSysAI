from app.extensions import db


class ExternalRequest(db.Model):
    """外部诉求——无需注册，通过公开 URL 提交。"""
    __tablename__ = 'external_requests'

    id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100))  # 提交人姓名
    contact = db.Column(db.String(200))  # 联系方式
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    urgency = db.Column(db.String(20), default='week')  # today/tomorrow/week
    status = db.Column(db.String(20), default='pending')  # pending/accepted/done/rejected
    response = db.Column(db.Text)  # 回复
    assigned_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: __import__('datetime').datetime.now())
    updated_at = db.Column(db.DateTime, default=lambda: __import__('datetime').datetime.now(),
                           onupdate=lambda: __import__('datetime').datetime.now())

    target_user = db.relationship('User', foreign_keys=[target_user_id], lazy='joined')
    assignee = db.relationship('User', foreign_keys=[assigned_id], lazy='joined')

    URGENCY_MAP = {
        'today': ('今天', 'danger'),
        'tomorrow': ('明天', 'warning'),
        'week': ('一周内', 'info'),
    }

    @property
    def urgency_label(self):
        return self.URGENCY_MAP.get(self.urgency, ('一周内', 'info'))[0]

    @property
    def urgency_color(self):
        return self.URGENCY_MAP.get(self.urgency, ('一周内', 'info'))[1]

    STATUS_MAP = {
        'pending': ('待处理', 'secondary'),
        'accepted': ('处理中', 'primary'),
        'done': ('已完成', 'success'),
        'rejected': ('已婉拒', 'secondary'),
    }

    @property
    def status_label(self):
        return self.STATUS_MAP.get(self.status, ('未知', 'secondary'))[0]

    @property
    def status_color(self):
        return self.STATUS_MAP.get(self.status, ('未知', 'secondary'))[1]
