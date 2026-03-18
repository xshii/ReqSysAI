from datetime import datetime

from app.extensions import db


class Todo(db.Model):
    __tablename__ = 'todos'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default='todo')  # todo / in_progress / done
    requirement_id = db.Column(db.Integer, db.ForeignKey('requirements.id'), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    estimated_hours = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref='todos')
    requirement = db.relationship('Requirement', backref='todos')

    def __repr__(self):
        return f'<Todo {self.title}>'
