from datetime import datetime

from app.extensions import db


class ProjectMember(db.Model):
    __tablename__ = 'project_members'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_role = db.Column(db.String(30), default='DEV')  # PM/PL/DEV/QA/UI
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', backref='members')
    user = db.relationship('User', backref='project_memberships')

    PROJECT_ROLES = {
        'PM': '项目经理',
        'PL': '技术负责人',
        'DEV': '开发',
        'QA': '测试',
        'UI': '设计',
    }

    @property
    def role_label(self):
        return self.PROJECT_ROLES.get(self.project_role, self.project_role)

    __table_args__ = (db.UniqueConstraint('project_id', 'user_id'),)
