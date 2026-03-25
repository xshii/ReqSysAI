from app.extensions import db


class EmailSetting(db.Model):
    __tablename__ = 'email_settings'

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(30), nullable=False)  # project_weekly / personal_weekly / meeting / aar
    entity_id = db.Column(db.Integer, nullable=False)  # project_id / user_id / meeting_id / project_id(aar)
    subject = db.Column(db.String(300), nullable=True)
    to_list = db.Column(db.Text, nullable=True)
    cc_list = db.Column(db.Text, nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        db.UniqueConstraint('entity_type', 'entity_id', name='uq_email_setting_entity'),
    )
