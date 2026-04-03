from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            abort(404)  # 假装页面不存在，不暴露后台
        return f(*args, **kwargs)
    return decorated_function


def manager_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_team_manager:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
