from datetime import datetime

from app.extensions import db


class Requirement(db.Model):
    __tablename__ = 'requirements'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)  # REQ-001
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    milestone_id = db.Column(db.Integer, db.ForeignKey('milestones.id'), nullable=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    status = db.Column(db.String(30), default='pending_review')
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    estimate_days = db.Column(db.Float, nullable=True)
    source = db.Column(db.String(50), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', back_populates='requirements')
    milestone = db.relationship('Milestone', backref='requirements')
    assignee = db.relationship('User', foreign_keys=[assignee_id], backref='assigned_requirements')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_requirements')
    tasks = db.relationship('RequirementTask', back_populates='requirement', cascade='all, delete-orphan')
    comments = db.relationship('Comment', back_populates='requirement', cascade='all, delete-orphan',
                               order_by='Comment.created_at')
    activities = db.relationship('Activity', back_populates='requirement', cascade='all, delete-orphan',
                                 order_by='Activity.created_at.desc()')

    STATUS_LABELS = {
        'pending_review': '待评估',
        'pending_dev': '待开发',
        'in_dev': '开发中',
        'in_test': '测试中',
        'done': '已完成',
        'closed': '已关闭',
    }

    STATUS_COLORS = {
        'pending_review': 'secondary',
        'pending_dev': 'dark',
        'in_dev': 'primary',
        'in_test': 'warning text-dark',
        'done': 'success',
        'closed': 'light text-dark border',
    }

    PRIORITY_LABELS = {'high': '高', 'medium': '中', 'low': '低'}
    PRIORITY_COLORS = {'high': 'danger', 'medium': 'warning text-dark', 'low': 'secondary'}

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


class RequirementTask(db.Model):
    __tablename__ = 'requirement_tasks'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requirement = db.relationship('Requirement', back_populates='tasks')

    STATUS_LABELS = {'pending': '待处理', 'in_progress': '进行中', 'done': '已完成'}

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)


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
