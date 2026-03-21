from datetime import datetime

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
    photo = db.Column(db.String(300), nullable=True)
    team_name = db.Column(db.String(100), nullable=True)  # legacy, kept for data compat
    external_nominees = db.Column(db.String(500), nullable=True)  # 非系统内人员，逗号分隔
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # 评审
    status = db.Column(db.String(20), default='pending')  # pending / approved / rejected
    review_comment = db.Column(db.String(150), nullable=True)  # 评语，上限150字
    amount = db.Column(db.Float, nullable=True)  # 激励金额
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        'pending':  ('待评审', 'warning text-dark'),
        'approved': ('已通过', 'success'),
        'rejected': ('已拒绝', 'danger'),
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
