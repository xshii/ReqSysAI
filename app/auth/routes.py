import logging
from datetime import datetime

from flask import redirect, url_for, flash, request, session, render_template, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app.auth import auth_bp
from app.auth.forms import LoginForm, RegisterForm, ProfileForm
from app.extensions import db, login_manager
from app.models.user import User, Role
from app.utils.pinyin import to_pinyin

logger = logging.getLogger(__name__)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def _get_client_ip():
    """Get real client IP, respecting proxy headers."""
    return request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login: enter employee_id, verify against current IP."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    client_ip = _get_client_ip()
    form = LoginForm()

    if form.validate_on_submit():
        eid = form.employee_id.data.strip().lower()
        user = User.query.filter_by(employee_id=eid).first()

        if not user:
            flash('工号未注册', 'danger')
            return render_template('auth/login.html', form=form, client_ip=client_ip)

        if not user.is_active:
            flash('账号已被禁用，请联系管理员', 'danger')
            return render_template('auth/login.html', form=form, client_ip=client_ip)

        if user.ip_address != client_ip:
            # IP changed — update binding
            logger.warning('IP changed for %s (%s): %s -> %s', user.employee_id, user.name, user.ip_address, client_ip)
            user.ip_address = client_ip
            db.session.commit()

        login_user(user, remember=False)
        session.permanent = True  # 10 min lifetime from config
        user.last_login = datetime.utcnow()
        db.session.commit()
        return redirect(url_for('main.index'))

    return render_template('auth/login.html', form=form, client_ip=client_ip)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """First-time user: enter employee_id + name, bind current IP."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    client_ip = _get_client_ip()
    form = RegisterForm()

    # Exclude Admin
    default_role_name = current_app.config.get('DEFAULT_ROLE', 'DE')
    roles = Role.query.filter(Role.name != 'Admin').order_by(Role.id).all()
    default_role = next((r for r in roles if r.name == default_role_name), roles[0] if roles else None)
    form.role_ids.choices = [(r.id, r.name) for r in roles]
    if not form.is_submitted() and default_role:
        form.role_ids.data = [default_role.id]

    groups = db.session.query(User.group).filter(
        User.group.isnot(None), User.group != ''
    ).distinct().order_by(User.group).all()
    form.group.choices = [('', '-- 暂不加入 --')] + [(g[0], g[0]) for g in groups]

    if form.validate_on_submit():
        eid = form.employee_id.data.strip().lower()

        existing = User.query.filter_by(employee_id=eid).first()
        if existing:
            flash(f'工号 {eid} 已被注册（{existing.name}），请直接登录', 'warning')
            return redirect(url_for('auth.login'))

        selected_roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        user = User(
            employee_id=eid,
            name=form.name.data,
            pinyin=to_pinyin(form.name.data),
            ip_address=client_ip,
            group=form.group.data or None,
            roles=selected_roles,
        )
        db.session.add(user)
        db.session.commit()
        flash(f'注册成功！{user.name}（{eid}）', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form, client_ip=client_ip)


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(obj=current_user)

    roles = Role.query.filter(Role.name != 'Admin').order_by(Role.id).all()
    form.role_ids.choices = [(r.id, r.name) for r in roles]
    if not form.is_submitted():
        form.role_ids.data = [r.id for r in current_user.roles if r.name != 'Admin']

    groups = db.session.query(User.group).filter(
        User.group.isnot(None), User.group != ''
    ).distinct().order_by(User.group).all()
    form.group.choices = [('', '-- 无 --')] + [(g[0], g[0]) for g in groups]

    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.pinyin = to_pinyin(form.name.data)
        # Keep Admin if user already has it, add selected roles
        admin_roles = [r for r in current_user.roles if r.name == 'Admin']
        selected_roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        current_user.roles = admin_roles + selected_roles
        current_user.group = form.group.data or None
        db.session.commit()
        flash('个人信息已更新', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))
