from app.extensions import db


class StandupRecord(db.Model):
    __tablename__ = 'standup_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    yesterday_done = db.Column(db.Text)
    today_plan = db.Column(db.Text)
    blocker = db.Column(db.Text)
    has_blocker = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    user = db.relationship('User', backref='standup_records')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='uq_standup_user_date'),
    )

    def __repr__(self):
        return f'<StandupRecord {self.user_id} {self.date}>'
