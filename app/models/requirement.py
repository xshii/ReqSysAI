from datetime import datetime

from app.extensions import db


class Requirement(db.Model):
    __tablename__ = 'requirements'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    milestone_id = db.Column(db.Integer, db.ForeignKey('milestones.id'), nullable=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')  # high / medium / low
    status = db.Column(db.String(30), default='pending_review')
    # Status flow: pending_review -> pending_dev -> in_dev -> in_test -> done -> closed
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    estimate_days = db.Column(db.Float, nullable=True)
    source = db.Column(db.String(50), nullable=True)  # manual / ai_chat / ai_docx
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', back_populates='requirements')
    milestone = db.relationship('Milestone', backref='requirements')
    assignee = db.relationship('User', foreign_keys=[assignee_id], backref='assigned_requirements')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_requirements')
    tasks = db.relationship('RequirementTask', back_populates='requirement', cascade='all, delete-orphan')

    # Status display mapping
    STATUS_LABELS = {
        'pending_review': '待评估',
        'pending_dev': '待开发',
        'in_dev': '开发中',
        'in_test': '测试中',
        'done': '已完成',
        'closed': '已关闭',
    }

    PRIORITY_LABELS = {
        'high': '高',
        'medium': '中',
        'low': '低',
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def priority_label(self):
        return self.PRIORITY_LABELS.get(self.priority, self.priority)

    def __repr__(self):
        return f'<Requirement {self.title}>'


class RequirementTask(db.Model):
    __tablename__ = 'requirement_tasks'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending / in_progress / done
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    requirement = db.relationship('Requirement', back_populates='tasks')
    assignee = db.relationship('User', backref='requirement_tasks')

    def __repr__(self):
        return f'<RequirementTask {self.title}>'
