from app.extensions import db

# 被推荐人多选
incentive_nominees = db.Table('incentive_nominees',
    db.Column('incentive_id', db.Integer, db.ForeignKey('incentives.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
)


class Incentive(db.Model):
    __tablename__ = 'incentives'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(30), default='professional')  # professional/proactive/beyond/clean
    description = db.Column(db.Text, nullable=False)

    CATEGORY_LABELS = {
        'professional': '专业',
        'proactive': '积极',
        'beyond': '超越期望',
        'clean': '代码Clean',
    }
    CATEGORY_COLORS = {
        'professional': 'primary',
        'proactive': 'success',
        'beyond': 'warning text-dark',
        'clean': 'info',
    }
    source = db.Column(db.String(30), default='instant')  # 激励来源

    @property
    def source_label(self):
        from app.constants import INCENTIVE_SOURCE_LABELS
        return INCENTIVE_SOURCE_LABELS.get(self.source, self.source)

    photo = db.Column(db.String(300), nullable=True)
    team_name = db.Column(db.String(100), nullable=True)  # 已废弃，待下次迁移删除
    external_nominees = db.Column(db.String(500), nullable=True)  # 非系统内人员，逗号分隔
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # 评审
    status = db.Column(db.String(20), default='submitted')  # submitted / pending / approved / rejected
    review_comment = db.Column(db.String(150), nullable=True)  # 评语，上限150字
    amount = db.Column(db.Float, nullable=True)  # 激励金额（总额）
    amount_detail = db.Column(db.String(200), nullable=True)  # 多人金额明细，如"500;300;800"
    fund_id = db.Column(db.Integer, db.ForeignKey('incentive_funds.id'), nullable=True)  # 关联资金条目
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    is_public = db.Column(db.Boolean, default=True)  # 首页对外可见
    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=db.func.now())

    fund = db.relationship('IncentiveFund', backref='incentives')
    submitter = db.relationship('User', foreign_keys=[submitted_by], backref='submitted_incentives')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_incentives')
    nominees = db.relationship('User', secondary=incentive_nominees, backref='nominated_incentives')

    @property
    def all_nominee_names(self):
        """All nominee names: system users + external."""
        names = [u.name for u in self.nominees]
        if self.external_nominees:
            names.extend(n.strip() for n in self.external_nominees.split(',') if n.strip())
        return names

    _STATUS_META = {
        'submitted': ('待评审', 'info'),
        'pending':   ('待修改', 'warning text-dark'),
        'approved':  ('已通过', 'success'),
        'rejected':  ('已拒绝', 'danger'),
    }
    STATUS_LABELS = {k: v[0] for k, v in _STATUS_META.items()}
    STATUS_COLORS = {k: v[1] for k, v in _STATUS_META.items()}

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)

    @property
    def category_color(self):
        return self.CATEGORY_COLORS.get(self.category, 'secondary')

    @property
    def award_type(self):
        """团队奖 or 个人奖, based on nominee count."""
        return '团队奖' if len(self.all_nominee_names) > 1 else '个人奖'

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    def __repr__(self):
        return f'<Incentive {self.title}>'


class IncentiveFund(db.Model):
    """Incentive fund pool — tracks budget per source with expiry."""
    __tablename__ = 'incentive_funds'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)  # 资金条目名称
    source = db.Column(db.String(30), nullable=False, default='instant')  # 激励来源
    total_amount = db.Column(db.Float, nullable=True)  # 总金额，空=公共池不限额
    expires_at = db.Column(db.Date, nullable=True)  # 截止使用日期
    note = db.Column(db.String(500), nullable=True)  # 备注
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    creator = db.relationship('User', backref='created_funds')

    @property
    def source_label(self):
        from app.constants import INCENTIVE_SOURCE_LABELS
        return INCENTIVE_SOURCE_LABELS.get(self.source, self.source)

    @property
    def used_amount(self):
        """Sum of approved incentive amounts linked to this fund (or by source fallback)."""
        # Prefer direct fund_id link
        direct = db.session.query(db.func.coalesce(db.func.sum(Incentive.amount), 0)).filter(
            Incentive.fund_id == self.id,
            Incentive.status == 'approved',
        ).scalar()
        if float(direct) > 0:
            return float(direct)
        # Fallback: match by source (for legacy data without fund_id)
        total = db.session.query(db.func.coalesce(db.func.sum(Incentive.amount), 0)).filter(
            Incentive.source == self.source,
            Incentive.fund_id.is_(None),
            Incentive.status == 'approved',
        ).scalar()
        return float(total)

    @property
    def has_budget(self):
        return self.total_amount is not None and self.total_amount > 0

    @property
    def remaining(self):
        if not self.has_budget:
            return None
        return self.total_amount - self.used_amount

    @property
    def is_expired(self):
        from datetime import date
        return self.expires_at and self.expires_at < date.today()

    def __repr__(self):
        return f'<IncentiveFund {self.name} ¥{self.total_amount}>'


class IncentiveReport(db.Model):
    """Persisted AI analysis report for incentive stats."""
    __tablename__ = 'incentive_reports'

    id = db.Column(db.Integer, primary_key=True)
    period = db.Column(db.String(10), nullable=False, default='1y')  # 3m/6m/1y/all
    data = db.Column(db.Text, nullable=False)  # JSON string
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())

    creator = db.relationship('User', backref='incentive_reports')
