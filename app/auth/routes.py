import logging
from datetime import datetime
from urllib.parse import urlparse

from flask import render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user

from app.auth import auth_bp
from app.auth.forms import LoginForm
from app.extensions import db, login_manager

logger = logging.getLogger(__name__)


@login_manager.user_loader
def load_user(user_id):
    from app.models.user import User
    return db.session.get(User, int(user_id))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = LoginForm()
    if form.validate_on_submit():
        from app.models.user import User

        user = User.query.filter_by(username=form.username.data).first()

        # Try local auth
        if user and user.auth_type == 'local' and user.check_password(form.password.data):
            return _do_login(user)

        # Try LDAP if configured
        if current_app.config.get('LDAP_HOST'):
            ldap_user = _try_ldap_auth(form.username.data, form.password.data)
            if ldap_user:
                return _do_login(ldap_user)

        flash('用户名或密码错误', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))


def _is_safe_url(target):
    """Validate that redirect target is a relative URL on the same host."""
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.scheme == '' and parsed.netloc == ''


def _do_login(user):
    if not user.is_active:
        flash('账号已被禁用，请联系管理员', 'danger')
        return redirect(url_for('auth.login'))
    login_user(user, remember=False)
    session.permanent = True
    user.last_login = datetime.utcnow()
    db.session.commit()
    next_page = request.args.get('next')
    if not _is_safe_url(next_page):
        next_page = None
    return redirect(next_page or url_for('main.index'))


def _try_ldap_auth(username, password):
    """Attempt LDAP authentication. On success, find or create local User record."""
    try:
        from app.extensions import ldap_manager
        from flask_ldap3_login import AuthenticationResponseStatus

        result = ldap_manager.authenticate(username, password)
        if result.status == AuthenticationResponseStatus.success:
            from app.models.user import User, Role

            user = User.query.filter_by(username=username).first()
            if not user:
                employee_role = Role.query.filter_by(name='employee').first()
                user = User(
                    username=username,
                    email=result.user_info.get('mail', f'{username}@company.com'),
                    display_name=result.user_info.get('cn', username),
                    auth_type='ldap',
                    ldap_dn=result.user_dn,
                    role=employee_role,
                )
                db.session.add(user)
                db.session.commit()
            return user
    except Exception:
        logger.exception('LDAP authentication error for user: %s', username)
    return None
