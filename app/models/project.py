from app.extensions import _local_now, db


class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='active')  # active / completed / archived / closed
    is_hidden = db.Column(db.Boolean, default=False)  # 仅管理层可见
    parent_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_local_now)
    updated_at = db.Column(db.DateTime, default=_local_now, onupdate=_local_now)

    parent = db.relationship('Project', remote_side=[id], backref='children')
    owner = db.relationship('User', foreign_keys=[owner_id], backref='owned_projects')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_projects')
    milestones = db.relationship('Milestone', back_populates='project', cascade='all, delete-orphan')
    requirements = db.relationship('Requirement', back_populates='project', lazy='dynamic')

    STATUS_LABELS = {'active': '进行中', 'completed': '已完成', 'closed': '已关闭'}

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def progress(self):
        total = self.requirements.count()
        if total == 0:
            return 0
        from app.models.requirement import Requirement
        done = self.requirements.filter(
            Requirement.status.in_(['done', 'closed'])
        ).count()
        return round(done / total * 100)

    def __repr__(self):
        return f'<Project {self.name}>'


class Milestone(db.Model):
    __tablename__ = 'milestones'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=_local_now)

    project = db.relationship('Project', back_populates='milestones')

    def __repr__(self):
        return f'<Milestone {self.name}>'


class MilestoneTemplate(db.Model):
    __tablename__ = 'milestone_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=_local_now)

    items = db.relationship('MilestoneTemplateItem', backref='template',
                            cascade='all, delete-orphan', order_by='MilestoneTemplateItem.sort_order')

    def __repr__(self):
        return f'<MilestoneTemplate {self.name}>'


class MilestoneTemplateItem(db.Model):
    __tablename__ = 'milestone_template_items'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('milestone_templates.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    offset_days = db.Column(db.Integer, default=0)  # 相对项目开始的天数偏移
    sort_order = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<MilestoneTemplateItem {self.name}>'
