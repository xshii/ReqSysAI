from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def role_required(*role_names):
    """Decorator: require login + one of the specified roles."""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if not current_user.has_role(*role_names):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """Shorthand for @role_required('admin')."""
    return role_required('admin')(f)
