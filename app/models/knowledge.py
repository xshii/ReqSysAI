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



class PermissionItem(db.Model):
    """权限目录：有哪些权限可以申请"""
    __tablename__ = 'permission_items'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    resource = db.Column(db.String(200), nullable=False)  # 群组名
    repo_path = db.Column(db.String(300), nullable=True)
    description = db.Column(db.String(300), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', backref='permission_items')
    creator = db.relationship('User')
    applications = db.relationship('PermissionApplication', back_populates='item',
                                   cascade='all, delete-orphan', order_by='PermissionApplication.created_at.desc()')


class PermissionApplication(db.Model):
    """申请记录：谁申请了什么权限，审批状态"""
    __tablename__ = 'permission_applications'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('permission_items.id'), nullable=False)
    applicant_name = db.Column(db.Text, nullable=False)  # 多人换行分隔：姓名(拼音) 工号
    applicant_eid = db.Column(db.String(30), nullable=True)  # 单人时的工号（兼容）
    reason = db.Column(db.String(300), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending/approved/rejected
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)

    item = db.relationship('PermissionItem', back_populates='applications')
    submitter = db.relationship('User', foreign_keys=[submitted_by])
    approver = db.relationship('User', foreign_keys=[approved_by])

    STATUS_LABELS = {'pending': '待审批', 'approved': '已通过', 'rejected': '已拒绝'}

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def people_list(self):
        """拆分多人名单为列表"""
        if not self.applicant_name:
            return []
        return [n.strip() for n in self.applicant_name.replace(',', '\n').split('\n') if n.strip()]

    @property
    def people_count(self):
        return len(self.people_list)


# Legacy model kept for migration compatibility
class PermissionRequest(db.Model):
    __tablename__ = 'permission_requests'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    resource = db.Column(db.String(200), nullable=False)
    repo_path = db.Column(db.String(300), nullable=True)
    description = db.Column(db.String(300), nullable=True)
    applicants = db.Column(db.Text, nullable=True)
    submitter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='draft')
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
        if '\n' in self.applicants:
            return [n.strip() for n in self.applicants.split('\n') if n.strip()]
        return [n.strip() for n in self.applicants.split(',') if n.strip()]
