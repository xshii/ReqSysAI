from datetime import datetime

from flask_login import UserMixin

from app.extensions import db

# Many-to-many association tables
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'), primary_key=True),
)

user_followed_projects = db.Table('user_followed_projects',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('project_id', db.Integer, db.ForeignKey('projects.id'), primary_key=True),
)


class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

    def __repr__(self):
        return f'<Role {self.name}>'


class Group(db.Model):
    """Independent group/team table. User.group stores the name string."""
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Group {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    ip_address = db.Column(db.String(45), unique=True, nullable=False, index=True)
    pinyin = db.Column(db.String(100), nullable=True)
    avatar = db.Column(db.String(300), nullable=True)  # 个人照片路径
    group = db.Column(db.String(50), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    pomodoro_minutes = db.Column(db.Integer, default=45)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    roles = db.relationship('Role', secondary=user_roles, backref='users', lazy='joined')
    followed_projects = db.relationship('Project', secondary=user_followed_projects, backref='followers', lazy='dynamic')

    TEAM_MANAGER_ROLES = {'Admin', 'PL', 'XM', 'HR'}

    @property
    def is_admin(self):
        return any(r.name == 'Admin' for r in self.roles)

    @property
    def is_team_manager(self):
        return any(r.name in self.TEAM_MANAGER_ROLES for r in self.roles)

    def has_role(self, *role_names):
        return any(r.name in role_names for r in self.roles)

    @property
    def role_names(self):
        """Comma-separated role names for display."""
        return ', '.join(r.name for r in self.roles)

    def __repr__(self):
        return f'<User {self.name}>'
