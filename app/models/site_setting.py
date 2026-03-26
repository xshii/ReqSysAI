from app.extensions import db


class SiteSetting(db.Model):
    """Key-value store for site-wide settings (editable from admin UI)."""
    __tablename__ = 'site_settings'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, default='')

    @staticmethod
    def get(key, default=''):
        row = SiteSetting.query.get(key)
        return row.value if row and row.value else default

    @staticmethod
    def set(key, value):
        row = SiteSetting.query.get(key)
        if row:
            row.value = value
        else:
            db.session.add(SiteSetting(key=key, value=value))
        db.session.commit()
