from datetime import date as _date, datetime as _dt

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import types


class _TolerantDateTime(types.TypeDecorator):
    """SQLite datetime that tolerates milliseconds, extra spaces, strings, etc."""
    impl = types.DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or isinstance(value, _dt):
            return value
        if isinstance(value, _date):
            return _dt(value.year, value.month, value.day)
        if isinstance(value, str):
            s = value.strip()
            for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                try:
                    return _dt.strptime(s, fmt)
                except ValueError:
                    continue
        return value

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, _dt):
            return value
        if isinstance(value, _date):
            return _dt(value.year, value.month, value.day)
        s = str(value).strip()
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return _dt.strptime(s, fmt)
            except ValueError:
                continue
        return value


class _TolerantDate(types.TypeDecorator):
    """SQLite date that tolerates datetime strings with time/milliseconds."""
    impl = types.Date
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or isinstance(value, _date) and not isinstance(value, _dt):
            return value
        if isinstance(value, _dt):
            return value.date()
        if isinstance(value, str):
            try:
                return _date.fromisoformat(value.strip().split('T')[0].split(' ')[0])
            except (ValueError, TypeError):
                pass
        return value

    def process_result_value(self, value, dialect):
        if value is None or isinstance(value, _date) and not isinstance(value, _dt):
            return value
        if isinstance(value, _dt):
            return value.date()
        s = str(value).strip().split('T')[0].split(' ')[0]
        try:
            return _date.fromisoformat(s)
        except (ValueError, TypeError):
            return value


db = SQLAlchemy()
# Override so all models using db.DateTime / db.Date get tolerant parsing
db.DateTime = _TolerantDateTime
db.Date = _TolerantDate
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'warning'
