from app.extensions import db

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
    status = db.Column(db.String(30), default='pending_review')
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    assignee_name = db.Column(db.String(100), nullable=True)  # 外部责任人（无系统账号时）
    estimate_days = db.Column(db.Float, nullable=True)
    code_lines = db.Column(db.Integer, nullable=True)  # 代码行数
    test_cases = db.Column(db.Integer, nullable=True)  # 测试用例数
    start_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=True)
    source = db.Column(db.String(50), default='coding')  # 需求类型: analysis/coding/testing
    category = db.Column(db.String(100), nullable=True)  # 需求分类
    ai_ratio = db.Column(db.Integer, nullable=True)  # AI辅助占比(%)
    completion = db.Column(db.Integer, default=0)  # 完成率(%) 0/30/60/90/100
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

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
        'pending_review': ('待启动', 'secondary'),
        'pending_dev':    ('分析中', 'dark'),
        'in_dev':         ('开发中', 'primary'),
        'in_test':        ('测试中', 'warning text-dark'),
        'done':           ('已完成', 'success'),
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

    CATEGORY_CHOICES = [
        ('feature', '功能需求'),
        ('bugfix', '缺陷修复'),
        ('optimization', '性能优化'),
        ('refactor', '代码重构'),
        ('infra', '基础设施'),
        ('doc', '文档'),
        ('other', '其他'),
    ]
    CATEGORY_LABELS = dict(CATEGORY_CHOICES)

    @property
    def source_label(self):
        return self.SOURCE_LABELS.get(self.source, self.source or '')

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category or '')

    ALLOWED_TRANSITIONS = {
        'pending_review': ['pending_dev'],
        'pending_dev': ['in_dev', 'pending_review'],
        'in_dev': ['in_test', 'pending_dev'],
        'in_test': ['done', 'in_dev'],
        'done': ['in_test'],
    }

    @property
    def weighted_completion(self):
        from app.constants import REQ_PHASE_ORDER, REQ_PHASE_WEIGHTS
        if self.status in ('done', 'closed'):
            return 100
        weights = REQ_PHASE_WEIGHTS.get(self.source or 'coding', REQ_PHASE_WEIGHTS['coding'])
        cur_pct = self.completion or 0
        cur_idx = REQ_PHASE_ORDER.index(self.status) if self.status in REQ_PHASE_ORDER else 0
        total = 0.0
        for phase, w in weights.items():
            phase_idx = REQ_PHASE_ORDER.index(phase)
            if phase_idx < cur_idx:
                total += w * 100
            elif phase_idx == cur_idx:
                total += w * cur_pct
        return round(total)

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
    created_at = db.Column(db.DateTime, default=db.func.now())

    requirement = db.relationship('Requirement', back_populates='comments')
    user = db.relationship('User', backref='comments')


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # created/status_changed/edited/commented/task_added
    detail = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=db.func.now())

    requirement = db.relationship('Requirement', back_populates='activities')
    user = db.relationship('User', backref='activities')
