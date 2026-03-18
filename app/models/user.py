from datetime import datetime

from flask_login import UserMixin

from app.extensions import db, bcrypt


class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200))

    users = db.relationship('User', back_populates='role', lazy='dynamic')

    def __repr__(self):
        return f'<Role {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=True)
    display_name = db.Column(db.String(80), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    auth_type = db.Column(db.String(20), default='local')  # 'local' or 'ldap'
    ldap_dn = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    role = db.relationship('Role', back_populates='users')

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        return bcrypt.check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role and self.role.name == 'admin'

    def has_role(self, *role_names):
        return self.role and self.role.name in role_names

    def __repr__(self):
        return f'<User {self.username}>'
