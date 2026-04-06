from app.extensions import db, _local_now


class IPChangeRequest(db.Model):
    __tablename__ = 'ip_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    old_ip = db.Column(db.String(50), nullable=False)
    new_ip = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending / approved / rejected
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_local_now)

    user = db.relationship('User', foreign_keys=[user_id], backref='ip_requests')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
