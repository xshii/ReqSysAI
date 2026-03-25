from app.extensions import db


class WeeklyReport(db.Model):
    __tablename__ = 'weekly_reports'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    week_start = db.Column(db.Date, nullable=False)  # Monday
    week_end = db.Column(db.Date, nullable=False)  # Sunday
    summary = db.Column(db.Text, nullable=True)  # AI 一句话进展
    risks_json = db.Column(db.Text, nullable=True)  # JSON array of risk strings
    plan_json = db.Column(db.Text, nullable=True)  # JSON array of plan strings
    content_html = db.Column(db.Text, nullable=True)
    is_frozen = db.Column(db.Boolean, default=False)  # 冻结后不可编辑/重新生成
    frozen_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    frozen_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    project = db.relationship('Project', backref='weekly_reports')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_reports')
    freezer = db.relationship('User', foreign_keys=[frozen_by])

    __table_args__ = (
        db.UniqueConstraint('project_id', 'week_start', name='uq_project_week'),
    )

    def __repr__(self):
        return f'<WeeklyReport {self.project_id} {self.week_start}>'


class PersonalWeekly(db.Model):
    """个人周报（AI 生成后自动保存，按 user + week_start 唯一）"""
    __tablename__ = 'personal_weeklies'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    week_start = db.Column(db.Date, nullable=False)
    week_end = db.Column(db.Date, nullable=False)
    ai_html = db.Column(db.Text, nullable=True)  # AI 生成的 HTML
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    user = db.relationship('User')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'week_start', name='uq_user_personal_week'),
    )
