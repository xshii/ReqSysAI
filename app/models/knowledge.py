from datetime import datetime

from app.extensions import db


class Knowledge(db.Model):
    __tablename__ = 'knowledges'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    link_type = db.Column(db.String(50), default='doc')  # 链接类型
    biz_category = db.Column(db.String(100), nullable=True)  # 业务分类（自定义）
    link = db.Column(db.String(500), nullable=True)
    is_pinned = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', backref='knowledges')
    creator = db.relationship('User')

    LINK_TYPES = {
        'wiki': 'Wiki',
        'code_demo': '代码Demo',
        'video': '视频',
        'doc': '文档',
        'design': '设计稿',
        'api': '接口文档',
        'other': '其他',
    }

    @property
    def link_type_label(self):
        return self.LINK_TYPES.get(self.link_type, self.link_type)



class PermissionRequest(db.Model):
    __tablename__ = 'permission_requests'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    category = db.Column(db.String(100), nullable=True)  # 分类（手动填写）
    resource = db.Column(db.String(200), nullable=False)  # 群组名
    repo_path = db.Column(db.String(300), nullable=True)  # 关联代码仓/dbox路径
    description = db.Column(db.String(300), nullable=True)  # 简要说明
    applicants = db.Column(db.Text, nullable=True)  # 申请人（逗号分隔，含外部）
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
        if not self.applicants:
            return []
        # Support both newline-separated (new format) and comma-separated (legacy)
        if '\n' in self.applicants:
            return [n.strip() for n in self.applicants.split('\n') if n.strip()]
        return [n.strip() for n in self.applicants.split(',') if n.strip()]
