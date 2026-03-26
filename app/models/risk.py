from datetime import date

from app.extensions import db


class Risk(db.Model):
    __tablename__ = 'risks'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(20), default='medium')  # high / medium / low
    status = db.Column(db.String(20), default='open')  # open / resolved / closed
    owner = db.Column(db.String(100), nullable=True)  # 责任人姓名（外部人员或显示名）
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 责任人（系统用户）
    tracker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 跟踪人（内部员工）
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=True)  # 关联子需求
    meeting_id = db.Column(db.Integer, db.ForeignKey('meetings.id'), nullable=True)  # 来源会议
    aar_id = db.Column(db.Integer, db.ForeignKey('aars.id'), nullable=True)  # 来源AAR
    due_date = db.Column(db.Date, nullable=False)
    resolution = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    resolved_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)  # 软删除
    deleted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    project = db.relationship('Project', backref='risks')
    owner_user = db.relationship('User', foreign_keys=[owner_id], backref='owned_risks')
    tracker = db.relationship('User', foreign_keys=[tracker_id], backref='tracked_risks')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_risks')
    requirement = db.relationship('Requirement', backref='risks')
    meeting = db.relationship('Meeting', backref='linked_risks')
    comments = db.relationship('RiskComment', backref='risk', cascade='all, delete-orphan',
                               order_by='RiskComment.created_at')

    _SEVERITY_META = {
        'high':   ('高', 'danger'),
        'medium': ('中', 'warning text-dark'),
        'low':    ('低', 'secondary'),
    }
    SEVERITY_LABELS = {k: v[0] for k, v in _SEVERITY_META.items()}
    SEVERITY_COLORS = {k: v[1] for k, v in _SEVERITY_META.items()}

    _STATUS_META = {
        'open':     ('未解决', 'danger'),
        'resolved': ('已解决', 'success'),
        'closed':   ('已关闭', 'secondary'),
    }
    STATUS_LABELS = {k: v[0] for k, v in _STATUS_META.items()}
    STATUS_COLORS = {k: v[1] for k, v in _STATUS_META.items()}

    @property
    def severity_label(self):
        return self.SEVERITY_LABELS.get(self.severity, self.severity)

    @property
    def severity_color(self):
        return self.SEVERITY_COLORS.get(self.severity, 'secondary')

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def is_overdue(self):
        return self.status == 'open' and self.due_date and self.due_date < date.today() and not self.is_deleted

    @property
    def is_due_today(self):
        return self.status == 'open' and self.due_date and self.due_date == date.today() and not self.is_deleted

    def __repr__(self):
        return f'<Risk {self.title}>'


class RiskAuditLog(db.Model):
    """Audit log for risk changes (create/edit/delete/resolve)."""
    __tablename__ = 'risk_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    risk_id = db.Column(db.Integer, db.ForeignKey('risks.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # created/edited/deleted/resolved/reopened
    detail = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    risk = db.relationship('Risk', backref='audit_logs')
    user = db.relationship('User', lazy='joined')


class RiskComment(db.Model):
    __tablename__ = 'risk_comments'

    id = db.Column(db.Integer, primary_key=True)
    risk_id = db.Column(db.Integer, db.ForeignKey('risks.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship('User', lazy='joined')
