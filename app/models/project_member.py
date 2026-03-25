from app.extensions import db


class ProjectMember(db.Model):
    __tablename__ = 'project_members'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # null = external
    external_name = db.Column(db.String(100), nullable=True)  # 外部成员姓名
    external_eid = db.Column(db.String(30), nullable=True)  # 外部成员工号
    project_role = db.Column(db.String(50), default='DEV')  # 支持自定义角色
    is_key = db.Column(db.Boolean, default=True)  # 关键角色标记，仅PM可见
    expected_ratio = db.Column(db.Integer, nullable=True)  # 预期投入比例(%)
    created_at = db.Column(db.DateTime, default=db.func.now())

    project = db.relationship('Project', backref='members')
    user = db.relationship('User', backref='project_memberships')

    DEFAULT_ROLES = {
        'PM': '项目经理',
        'PL': '技术负责人',
        'DEV': '开发',
        'TE': '测试',
        'QA': '质量管理',
        'UI': '设计',
    }

    @property
    def display_name(self):
        if self.user:
            return self.user.name
        return self.external_name or '未知'

    @property
    def display_eid(self):
        if self.user:
            return self.user.employee_id
        return self.external_eid or ''

    @property
    def role_label(self):
        return self.DEFAULT_ROLES.get(self.project_role, self.project_role)
