from datetime import datetime

from app.extensions import db


class Knowledge(db.Model):
    __tablename__ = 'knowledges'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    category = db.Column(db.String(50), default='doc')  # doc/design/api/wiki/other
    link = db.Column(db.String(500), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', backref='knowledges')
    creator = db.relationship('User')

    CATEGORY_LABELS = {
        'doc': '文档',
        'design': '设计稿',
        'api': '接口文档',
        'wiki': 'Wiki',
        'other': '其他',
    }

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)


class PermissionRequest(db.Model):
    __tablename__ = 'permission_requests'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    resource = db.Column(db.String(200), nullable=False)  # 群组名/代码仓
    applicants = db.Column(db.Text, nullable=False)  # 申请人（逗号分隔，含外部）
    submitter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='draft')  # draft/submitted/approved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', backref='permission_requests')
    submitter = db.relationship('User')

    STATUS_LABELS = {'draft': '草稿', 'submitted': '已提交审批', 'approved': '审批完成'}

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def applicant_list(self):
        return [n.strip() for n in self.applicants.split(',') if n.strip()]
