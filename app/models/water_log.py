from app.extensions import _local_now, db


class WaterLog(db.Model):
    __tablename__ = 'water_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ml = db.Column(db.Integer, nullable=False)  # 250 / 500 / 750
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=_local_now)

    user = db.relationship('User', backref='water_logs')
