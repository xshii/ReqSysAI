from datetime import datetime

from app.extensions import db


class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')  # active / completed / archived
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = db.relationship('User', backref='created_projects')
    milestones = db.relationship('Milestone', back_populates='project', cascade='all, delete-orphan')
    requirements = db.relationship('Requirement', back_populates='project', lazy='dynamic')

    STATUS_LABELS = {'active': '进行中', 'completed': '已完成', 'archived': '已归档'}

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def progress(self):
        total = self.requirements.count()
        if total == 0:
            return 0
        from app.models.requirement import Requirement
        done = self.requirements.filter(
            Requirement.status.in_(['done', 'closed'])
        ).count()
        return round(done / total * 100)

    def __repr__(self):
        return f'<Project {self.name}>'


class Milestone(db.Model):
    __tablename__ = 'milestones'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', back_populates='milestones')

    def __repr__(self):
        return f'<Milestone {self.name}>'
