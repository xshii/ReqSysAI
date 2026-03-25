from app.extensions import db


class Rant(db.Model):
    """Anonymous rant wall. No IP, no user tracking."""
    __tablename__ = 'rants'

    id = db.Column(db.Integer, primary_key=True)
    alias = db.Column(db.String(30), nullable=True)
    content = db.Column(db.String(500), nullable=False)
    likes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=db.func.now())
    # Intentionally NO user_id, NO ip_address

    def __repr__(self):
        return f'<Rant {self.id}>'
