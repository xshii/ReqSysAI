import logging
from datetime import datetime, timezone

from flask import redirect, url_for, flash, request, session, render_template, current_app, jsonify
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
    """Get real client IP, respecting proxy headers. Supports DEV_CLIENT_IP override for local dev."""
    import os
    override = os.environ.get('DEV_CLIENT_IP')
    if override:
        return override
    return request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login: enter employee_id, verify against current IP."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    client_ip = _get_client_ip()

    # Auto-login by IP: if a user is bound to this IP, login directly
    # Skip if user just logged out (prevent immediate re-login)
    if session.pop('_logged_out', False):
        auto_user = None
    else:
        # Support comma-separated multi-IP (e.g. "192.168.1.100,127.0.0.1")
        # Use exact match first, then check comma-separated with boundary matching
        auto_user = User.query.filter_by(ip_address=client_ip).first()
        if not auto_user:
            # Match ",IP," or "IP," (start) or ",IP" (end) to avoid partial matches
            candidates = User.query.filter(
                User.ip_address.contains(client_ip)
            ).all()
            for u in candidates:
                if client_ip in [ip.strip() for ip in u.ip_address.split(',')]:
                    auto_user = u
                    break
    if auto_user and request.method == 'GET':
        login_user(auto_user, remember=False)
        session.permanent = True
        auto_user.last_login = datetime.now(timezone.utc)
        db.session.commit()
        # Clear "请先登录" flash message from login_required redirect
        session.pop('_flashes', None)
        return redirect(url_for('main.index'))

    form = LoginForm()

    if form.validate_on_submit():
        eid = form.employee_id.data.strip().lower()
        user = User.query.filter_by(employee_id=eid).first()

        if not user:
            flash('工号未注册', 'danger')
            form.employee_id.data = ''
            return render_template('auth/login.html', form=form, client_ip=client_ip)

        bound_ips = [ip.strip() for ip in user.ip_address.split(',')]
        if user.ip_address.startswith('pending-'):
            # First login: bind IP
            user.ip_address = client_ip
            db.session.commit()
        elif client_ip not in bound_ips:
            # Check if there's already a pending request
            from app.models.ip_request import IPChangeRequest
            pending = IPChangeRequest.query.filter_by(
                user_id=user.id, status='pending'
            ).first()
            if pending:
                flash('IP 更换申请已提交，请等待管理员审批', 'warning')
            else:
                flash(f'IP 不匹配（当前 {client_ip}，绑定 {user.ip_address}）', 'danger')
            return render_template('auth/login.html', form=form, client_ip=client_ip,
                                   ip_mismatch=True, mismatch_eid=user.employee_id,
                                   has_pending=bool(pending))

        login_user(user, remember=False)
        session.permanent = True  # 10 min lifetime from config
        user.last_login = datetime.now(timezone.utc)
        db.session.commit()
        return redirect(url_for('main.index'))

    return render_template('auth/login.html', form=form, client_ip=client_ip)


@auth_bp.route('/request-ip-change', methods=['POST'])
def request_ip_change():
    """Submit IP change request (no login required)."""
    from app.models.ip_request import IPChangeRequest
    eid = request.form.get('employee_id', '').strip().lower()
    client_ip = _get_client_ip()
    user = User.query.filter_by(employee_id=eid).first()
    if not user:
        flash('工号不存在', 'danger')
        return redirect(url_for('auth.login'))
    # Check duplicate
    pending = IPChangeRequest.query.filter_by(user_id=user.id, status='pending').first()
    if pending:
        flash('已有待审批的申请，请等待', 'warning')
        return redirect(url_for('auth.login'))
    req = IPChangeRequest(user_id=user.id, old_ip=user.ip_address, new_ip=client_ip)
    db.session.add(req)
    db.session.commit()
    flash('IP 更换申请已提交，请等待管理员审批', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """First-time user: enter employee_id + name, bind current IP."""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    client_ip = _get_client_ip()
    form = RegisterForm()

    # Exclude Admin and hidden roles (PL, XM, HR)
    default_role_name = current_app.config.get('DEFAULT_ROLE', 'DE')
    hidden = set(current_app.config.get('HIDDEN_ROLES', []) + ['Admin'])
    roles = Role.query.filter(Role.name.notin_(hidden)).order_by(Role.id).all()
    default_role = next((r for r in roles if r.name == default_role_name), roles[0] if roles else None)
    form.role_ids.choices = [(r.id, r.name) for r in roles]
    if not form.is_submitted() and default_role:
        form.role_ids.data = [default_role.id]

    from app.models.user import Group
    all_groups = Group.query.order_by(Group.name).all()
    form.group.choices = [('', '-- 暂不加入 --')] + [(g.name, g.name) for g in all_groups]

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

    hidden = set(current_app.config.get('HIDDEN_ROLES', []) + ['Admin'])
    roles = Role.query.filter(Role.name.notin_(hidden)).order_by(Role.id).all()
    form.role_ids.choices = [(r.id, r.name) for r in roles]
    if not form.is_submitted():
        form.role_ids.data = [r.id for r in current_user.roles if r.name not in hidden]

    from app.models.user import Group
    all_groups = Group.query.order_by(Group.name).all()
    form.group.choices = [('', '-- 无 --')] + [(g.name, g.name) for g in all_groups]

    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.pinyin = to_pinyin(form.name.data)
        # Keep Admin and hidden roles, add user-selected roles
        kept_roles = [r for r in current_user.roles if r.name in hidden]
        selected_roles = Role.query.filter(Role.id.in_(form.role_ids.data)).all()
        current_user.roles = kept_roles + selected_roles
        current_user.group = form.group.data or None
        current_user.pomodoro_minutes = request.form.get('pomodoro_minutes', type=int) or 45
        # Handle avatar upload
        from app.utils.upload import save_photo
        new_avatar = save_photo(request.files.get('avatar'), folder='avatar')
        if new_avatar:
            # Delete old avatar
            if current_user.avatar:
                import os
                old_path = os.path.join(current_app.root_path, 'static', current_user.avatar)
                if os.path.exists(old_path):
                    os.remove(old_path)
            current_user.avatar = new_avatar
        db.session.commit()
        flash('个人信息已更新', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', form=form)


@auth_bp.route('/profile/toggle-my-group', methods=['POST'])
@login_required
def toggle_my_group():
    current_user.only_my_group = not current_user.only_my_group
    db.session.commit()
    return jsonify(ok=True, only_my_group=current_user.only_my_group)


@auth_bp.route('/profile/stats')
@login_required
def profile_stats():
    """Personal efficiency dashboard."""
    from datetime import date, timedelta
    from app.models.todo import Todo
    from app.models.requirement import Requirement
    from app.models.incentive import Incentive
    from app.constants import TODO_STATUS_DONE, HEATMAP_DAYS

    today = date.today()
    uid = current_user.id

    # Monthly todo trend (last 6 months)
    six_months_ago = today - timedelta(days=180)
    monthly_todos = db.session.query(
        db.func.strftime('%Y-%m', Todo.done_date).label('month'),
        db.func.count(Todo.id),
    ).filter(
        Todo.user_id == uid, Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= six_months_ago,
    ).group_by('month').order_by('month').all()

    # Focus time (actual_minutes) aggregated by month
    monthly_focus = db.session.query(
        db.func.strftime('%Y-%m', Todo.done_date).label('month'),
        db.func.sum(Todo.actual_minutes),
    ).filter(
        Todo.user_id == uid, Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= six_months_ago, Todo.actual_minutes > 0,
    ).group_by('month').order_by('month').all()

    # Requirements participated (assigned)
    req_count = Requirement.query.filter_by(assignee_id=uid).count()
    req_done = Requirement.query.filter_by(assignee_id=uid, status='done').count()

    # Incentives received
    incentive_count = db.session.query(db.func.count(Incentive.id)).filter(
        Incentive.status == 'approved',
        Incentive.nominees.any(id=uid),
    ).scalar() or 0

    # Contribution heatmap (365 days for annual view)
    year_ago = today - timedelta(days=365)
    heatmap_rows = db.session.query(
        Todo.done_date, db.func.count(Todo.id),
    ).filter(
        Todo.user_id == uid, Todo.status == TODO_STATUS_DONE,
        Todo.done_date >= year_ago,
    ).group_by(Todo.done_date).all()
    heatmap = {str(row[0]): row[1] for row in heatmap_rows}

    # Total focus hours
    total_focus = db.session.query(
        db.func.sum(Todo.actual_minutes),
    ).filter(Todo.user_id == uid, Todo.actual_minutes > 0).scalar() or 0

    return render_template('auth/stats.html',
        monthly_todos=monthly_todos, monthly_focus=monthly_focus,
        req_count=req_count, req_done=req_done,
        incentive_count=incentive_count,
        heatmap=heatmap, heatmap_start=year_ago, today=today,
        total_focus_hours=round(total_focus / 60, 1),
        timedelta=timedelta,
    )


@auth_bp.route('/profile/ai-efficiency', methods=['POST'])
@login_required
def ai_efficiency():
    """AI analyzes personal work efficiency."""
    from datetime import date, timedelta
    from app.models.todo import Todo
    from app.models.requirement import Requirement
    from app.services.ai import call_ollama
    from app.services.prompts import get_prompt
    import markdown as md_lib

    today = date.today()
    uid = current_user.id
    d30 = today - timedelta(days=30)
    d7 = today - timedelta(days=7)

    # 30-day stats
    done_30d = Todo.query.filter(Todo.user_id == uid, Todo.status == 'done',
                                  Todo.created_date >= d30).count()
    done_7d = Todo.query.filter(Todo.user_id == uid, Todo.status == 'done',
                                 Todo.created_date >= d7).count()
    active = Todo.query.filter_by(user_id=uid, status='todo').count()
    blocked = Todo.query.filter(Todo.user_id == uid, Todo.status == 'todo',
                                 Todo.need_help == True).count()
    help_given = Todo.query.filter(Todo.user_id == uid, Todo.source == 'help',
                                    Todo.created_date >= d30).count()
    focus_30d = db.session.query(db.func.sum(Todo.actual_minutes)).filter(
        Todo.user_id == uid, Todo.created_date >= d30).scalar() or 0
    # Requirements
    req_total = Requirement.query.filter_by(assignee_id=uid).count()
    req_done = Requirement.query.filter_by(assignee_id=uid, status='done').count()
    req_overdue = Requirement.query.filter(
        Requirement.assignee_id == uid,
        Requirement.status.notin_(('done', 'closed')),
        Requirement.due_date < today).count()

    # Code stats
    total_code = db.session.query(db.func.sum(Requirement.code_lines)).filter(
        Requirement.assignee_id == uid, Requirement.code_lines.isnot(None)).scalar() or 0
    total_tests = db.session.query(db.func.sum(Requirement.test_cases)).filter(
        Requirement.assignee_id == uid, Requirement.test_cases.isnot(None)).scalar() or 0

    lines = [
        f'{current_user.name}（{current_user.role_names}，{current_user.group or ""}）的工作数据：',
        f'',
        f'近30天：完成 {done_30d} 个任务（日均 {round(done_30d/30,1)}），专注 {focus_30d} 分钟（日均 {round(focus_30d/30)}分钟）',
        f'近7天：完成 {done_7d} 个任务（日均 {round(done_7d/7,1)}）',
        f'当前进行中 {active} 个，阻塞 {blocked} 个',
        f'协助他人 {help_given} 次（近30天）',
        f'负责需求 {req_total} 个，已完成 {req_done} 个，延期 {req_overdue} 个',
        f'累计代码量 {total_code} 行，测试用例 {total_tests} 个' if total_code or total_tests else '',
    ]
    # Recurring todo discipline
    from app.models.recurring_todo import RecurringTodo
    from app.models.recurring_completion import RecurringCompletion
    recurring_all = RecurringTodo.query.filter_by(user_id=uid, is_active=True).all()
    if recurring_all:
        recurring_total = RecurringCompletion.query.filter(
            RecurringCompletion.user_id == uid,
            RecurringCompletion.recurring_id.in_([r.id for r in recurring_all]),
        ).count()
        lines.append(f'周期任务 {len(recurring_all)} 个，历史完成 {recurring_total} 次')

    prompt = get_prompt('personal_efficiency') + '\n\n' + '\n'.join(lines)
    _, raw = call_ollama(prompt)

    if raw:
        html = md_lib.markdown(raw, extensions=['tables'])
        return jsonify(ok=True, html=html)
    return jsonify(ok=False, error='分析失败')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    session['_logged_out'] = True
    flash('已退出登录', 'info')
    return redirect(url_for('auth.login'))
