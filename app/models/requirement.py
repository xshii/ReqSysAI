from datetime import datetime

from app.extensions import db


class Requirement(db.Model):
    __tablename__ = 'requirements'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)  # REQ-001
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    milestone_id = db.Column(db.Integer, db.ForeignKey('milestones.id'), nullable=True)  # legacy
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    status = db.Column(db.String(30), default='pending_review')
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assignee_name = db.Column(db.String(100), nullable=True)  # 外部责任人（无系统账号时）
    estimate_days = db.Column(db.Float, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=True)
    source = db.Column(db.String(50), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = db.relationship('Requirement', remote_side=[id], backref='children')
    project = db.relationship('Project', back_populates='requirements')
    assignee = db.relationship('User', foreign_keys=[assignee_id], backref='assigned_requirements')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_requirements')

    @property
    def assignee_display(self):
        if self.assignee:
            return self.assignee.name
        return self.assignee_name or '未分配'
    comments = db.relationship('Comment', back_populates='requirement', cascade='all, delete-orphan',
                               order_by='Comment.created_at')
    activities = db.relationship('Activity', back_populates='requirement', cascade='all, delete-orphan',
                                 order_by='Activity.created_at.desc()')

    # Single source of truth: (label, color)
    _STATUS_META = {
        'pending_review': ('待评估', 'secondary'),
        'pending_dev':    ('待开发', 'dark'),
        'in_dev':         ('开发中', 'primary'),
        'in_test':        ('测试中', 'warning text-dark'),
        'done':           ('已完成', 'success'),
        'closed':         ('已关闭', 'light text-dark border'),
    }
    STATUS_LABELS = {k: v[0] for k, v in _STATUS_META.items()}
    STATUS_COLORS = {k: v[1] for k, v in _STATUS_META.items()}

    _PRIORITY_META = {
        'high':   ('高', 'danger'),
        'medium': ('中', 'warning text-dark'),
        'low':    ('低', 'secondary'),
    }
    PRIORITY_LABELS = {k: v[0] for k, v in _PRIORITY_META.items()}
    PRIORITY_COLORS = {k: v[1] for k, v in _PRIORITY_META.items()}

    ALLOWED_TRANSITIONS = {
        'pending_review': ['pending_dev', 'closed'],
        'pending_dev': ['in_dev', 'pending_review', 'closed'],
        'in_dev': ['in_test', 'pending_dev', 'closed'],
        'in_test': ['done', 'in_dev', 'closed'],
        'done': ['closed', 'in_test'],
        'closed': ['pending_review'],
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    @property
    def priority_label(self):
        return self.PRIORITY_LABELS.get(self.priority, self.priority)

    @property
    def priority_color(self):
        return self.PRIORITY_COLORS.get(self.priority, 'secondary')

    @property
    def allowed_next_statuses(self):
        return self.ALLOWED_TRANSITIONS.get(self.status, [])

    @staticmethod
    def generate_number():
        result = db.session.query(
            db.func.max(
                db.func.cast(
                    db.func.substr(Requirement.number, 5), db.Integer
                )
            )
        ).scalar()
        seq = (result + 1) if result else 1
        return f'REQ-{seq:03d}'

    def __repr__(self):
        return f'<Requirement {self.number}>'


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requirement = db.relationship('Requirement', back_populates='comments')
    user = db.relationship('User', backref='comments')


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # created/status_changed/edited/commented/task_added
    detail = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requirement = db.relationship('Requirement', back_populates='activities')
    user = db.relationship('User', backref='activities')
