from datetime import datetime

from app.extensions import db


class Meeting(db.Model):
    __tablename__ = 'meetings'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    title = db.Column(db.String(300), nullable=False)
    date = db.Column(db.Date, nullable=False)
    attendees = db.Column(db.Text, nullable=True)  # comma-separated names
    content = db.Column(db.Text, nullable=True)  # raw minutes text
    ai_result = db.Column(db.Text, nullable=True)  # JSON string of extracted items
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', backref='meetings')
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_meetings')

    @property
    def has_extraction(self):
        return self.ai_result is not None and self.ai_result.strip() != ''

    @property
    def attendee_list(self):
        if not self.attendees:
            return []
        return [a.strip() for a in self.attendees.split(',') if a.strip()]

    def __repr__(self):
        return f'<Meeting {self.title}>'
