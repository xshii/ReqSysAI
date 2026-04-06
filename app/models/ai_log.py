from app.extensions import _local_now, db


class AIParseLog(db.Model):
    __tablename__ = 'ai_parse_logs'

    id = db.Column(db.Integer, primary_key=True)
    input_type = db.Column(db.String(30), nullable=False)  # chat_text / docx
    raw_input = db.Column(db.Text, nullable=False)
    ai_output = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_local_now)

    creator = db.relationship('User', backref='ai_parse_logs')

    def __repr__(self):
        return f'<AIParseLog {self.id}>'
