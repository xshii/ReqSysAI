from app.extensions import db, _local_now

# Many-to-many: requirement dependencies
requirement_dependencies = db.Table(
    'requirement_dependencies',
    db.Column('from_id', db.Integer, db.ForeignKey('requirements.id'), primary_key=True),
    db.Column('to_id', db.Integer, db.ForeignKey('requirements.id'), primary_key=True),
)


class Requirement(db.Model):
    __tablename__ = 'requirements'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False, index=True)  # REQ-001
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    milestone_id = db.Column(db.Integer, db.ForeignKey('milestones.id'), nullable=True)  # 已废弃，待下次迁移删除
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='medium')
    status = db.Column(db.String(30), default='pending')
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assignee_name = db.Column(db.String(100), nullable=True)  # 外部责任人（无系统账号时）
    estimate_days = db.Column(db.Float, nullable=True)
    code_lines = db.Column(db.Integer, nullable=True)  # 代码行数
    test_cases = db.Column(db.Integer, nullable=True)  # 测试用例数
    start_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=True)
    source = db.Column(db.String(50), default='coding')  # 需求类型: analysis/coding/testing
    category = db.Column(db.String(100), nullable=True)  # 业务分类: "模型名-软件/EDA/FPGA"
    ai_ratio = db.Column(db.Integer, nullable=True)  # AI辅助占比(%)
    completion = db.Column(db.Integer, default=0)  # 完成率(%) 0/30/60/90/100
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_local_now)
    updated_at = db.Column(db.DateTime, default=_local_now, onupdate=_local_now)

    parent = db.relationship('Requirement', remote_side=[id], backref='children')
    project = db.relationship('Project', back_populates='requirements')
    assignee = db.relationship('User', foreign_keys=[assignee_id], backref='assigned_requirements')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_requirements')

    # Dependencies: this requirement depends on (blocked by) these
    dependencies = db.relationship(
        'Requirement', secondary=requirement_dependencies,
        primaryjoin='Requirement.id == requirement_dependencies.c.from_id',
        secondaryjoin='Requirement.id == requirement_dependencies.c.to_id',
        backref='dependents',
    )

    @property
    def assignee_display(self):
        if self.assignee:
            return self.assignee.name
        return self.assignee_name or '未分配'
    comments = db.relationship('Comment', back_populates='requirement', cascade='all, delete-orphan',
                               order_by='Comment.created_at.desc()')
    activities = db.relationship('Activity', back_populates='requirement', cascade='all, delete-orphan',
                                 order_by='Activity.created_at.desc()')

    # Single source of truth: (label, color)
    _STATUS_META = {
        'pending':     ('待启动', 'secondary'),
        'in_progress': ('进行中', 'primary'),
        'done':        ('已完成', 'success'),
        'closed':      ('已取消', 'dark'),
    }
    # Backward compat: old statuses map to new ones
    _STATUS_COMPAT = {
        'pending_review': 'pending',
        'pending_dev': 'pending',
        'in_dev': 'in_progress',
        'in_test': 'in_progress',
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

    SOURCE_LABELS = {
        'analysis': '分析',
        'coding': '编码',
        'testing': '测试',
    }

    CATEGORY_L2_CHOICES = ['软件', 'EDA', 'FPGA']

    @property
    def source_label(self):
        return self.SOURCE_LABELS.get(self.source, self.source or '')

    @property
    def category_label(self):
        return self.category or ''

    @property
    def category_l1(self):
        """一级分类（模型名），从 category 按 '-' 切割"""
        if self.category and '-' in self.category:
            return self.category.split('-', 1)[0]
        return self.category or ''

    @property
    def category_l2(self):
        """二级分类（软件/EDA/FPGA），从 category 按 '-' 切割"""
        if self.category and '-' in self.category:
            return self.category.split('-', 1)[1]
        return ''

    ALLOWED_TRANSITIONS = {
        'pending': ['in_progress'],
        'in_progress': ['done', 'pending'],
        'done': ['in_progress'],
        'closed': ['pending'],
    }

    @property
    def weighted_completion(self):
        if self.status in ('done', 'closed'):
            return 100
        return self.completion or 0

    @property
    def status_label(self):
        s = self._STATUS_COMPAT.get(self.status, self.status)
        return self.STATUS_LABELS.get(s, s)

    @property
    def status_color(self):
        s = self._STATUS_COMPAT.get(self.status, self.status)
        return self.STATUS_COLORS.get(s, 'secondary')

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

    @staticmethod
    def generate_child_number(parent_number):
        """Generate child requirement number like REQ-001-1, REQ-001-2."""
        existing = db.session.query(db.func.count(Requirement.id)).filter(
            Requirement.number.like(f'{parent_number}-%')
        ).scalar() or 0
        return f'{parent_number}-{existing + 1}'

    def __repr__(self):
        return f'<Requirement {self.number}>'


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_local_now)

    requirement = db.relationship('Requirement', back_populates='comments')
    user = db.relationship('User', backref='comments')


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # created/status_changed/edited/commented/task_added
    detail = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=_local_now)

    requirement = db.relationship('Requirement', back_populates='activities')
    user = db.relationship('User', backref='activities')
