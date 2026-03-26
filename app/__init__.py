import os

from flask import Flask

from config import config


def create_app(config_name=None):
    app = Flask(__name__)
    config_name = config_name or os.getenv('FLASK_ENV', 'development')
    app.config.from_object(config[config_name])

    # Initialize extensions
    from app.extensions import csrf, db, login_manager, migrate
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    app.config['WTF_CSRF_ENABLED'] = False  # Internal app, IP-based auth

    # Import models so they are registered with SQLAlchemy
    from app import models  # noqa: F401
    from app.admin import admin_bp
    from app.ai import ai_bp

    # Register blueprints
    from app.auth import auth_bp
    from app.dashboard import dashboard_bp
    from app.main import main_bp
    from app.project import project_bp
    from app.requirement import requirement_bp
    from app.todo import todo_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(project_bp, url_prefix='/projects')
    app.register_blueprint(requirement_bp, url_prefix='/requirements')
    app.register_blueprint(ai_bp, url_prefix='/ai')
    app.register_blueprint(todo_bp, url_prefix='/todos')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

    from app.incentive import incentive_bp
    app.register_blueprint(incentive_bp, url_prefix='/incentive')

    # Register error handlers
    _register_error_handlers(app)

    # Domain events
    from app.services.event_setup import register_events
    register_events()


    @app.after_request
    def _no_cache(response):
        if 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-store'
        return response

    # Template filters
    import json as _json
    app.jinja_env.filters['from_json'] = lambda s: _json.loads(s) if s else []
    from app.utils.pinyin import to_pinyin as _to_pinyin
    app.jinja_env.filters['to_pinyin'] = lambda s: _to_pinyin(s).split()[-1] if s else ''

    # Inject sidebar groups into all templates
    @app.context_processor
    def inject_sidebar_groups():
        from flask import request as req
        from flask_login import current_user
        if current_user.is_authenticated:
            from app.models.project import Project
            from app.models.user import Group
            all_groups = Group.query.order_by(Group.name).all()
            # Default: only own group. User can toggle only_my_group=False in profile to see all.
            if current_user.only_my_group:
                # Explicitly opted to see only own group
                groups = [g.name for g in all_groups if g.name == current_user.group]
            else:
                # Show all non-hidden groups
                groups = [g.name for g in all_groups if not g.is_hidden]
            cur_group = req.args.get('group', current_user.group or '')
            if not cur_group and groups:
                cur_group = groups[0]
            # 侧边栏项目：隐藏项目仅管理层+eye打开时显示（隐私模式 cookie mgr_view）
            _show_hidden = current_user.is_team_manager and req.cookies.get('mgr_view') == '1'
            _pq = Project.query.filter_by(status='active')
            if not _show_hidden:
                _pq = _pq.filter_by(is_hidden=False)
            all_projects = _pq.order_by(Project.name).all()
            followed_ids = set(p.id for p in current_user.followed_projects.all())
            # Followed projects first, then others
            followed = [p for p in all_projects if p.id in followed_ids]
            unfollowed = [p for p in all_projects if p.id not in followed_ids]
            projects = followed + unfollowed

            # Notification counts for navbar bell — must match homepage bars
            from datetime import date

            from app.models.requirement import Requirement
            from app.models.risk import Risk
            today = date.today()
            # Alerts: overdue reqs + overdue risks (same as homepage)
            my_reqs_nav = Requirement.query.filter_by(assignee_id=current_user.id)\
                .filter(Requirement.status.notin_(('done', 'closed')),
                        Requirement.due_date < today).all()
            my_risks_nav = Risk.query.filter(
                Risk.status == 'open', Risk.deleted_at.is_(None),
                db.or_(Risk.tracker_id == current_user.id, Risk.owner_id == current_user.id),
            ).all()
            alerts_count = sum(1 for r in my_reqs_nav if r.due_date and r.due_date <= today) \
                + sum(1 for r in my_risks_nav if r.is_overdue or r.is_due_today)
            # Help todos
            from app.models.todo import Todo
            help_count = Todo.query.filter(
                Todo.user_id == current_user.id,
                Todo.parent_id.isnot(None),
                Todo.status == 'todo',
                Todo.source == 'help',
            ).count()
            # Persistent notifications
            from app.models.notification import Notification
            notif_persistent = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            notif_count = alerts_count + help_count + notif_persistent

            return dict(sidebar_groups=groups, sidebar_cur_group=cur_group,
                        sidebar_projects=projects, sidebar_followed_ids=followed_ids,
                        notif_count=notif_count,
                        ai_enabled=app.config.get('AI_ENABLED', True),
                        site_name=_get_site_name(app))
        return dict(sidebar_groups=[], sidebar_cur_group='', sidebar_projects=[],
                    sidebar_followed_ids=set(), notif_count=0,
                    site_name=_get_site_name(app))

    return app


def _get_site_name(app):
    """Read site_name from DB (SiteSetting) first, fallback to config."""
    try:
        from app.models.site_setting import SiteSetting
        val = SiteSetting.get('site_name')
        if val:
            return val
    except Exception:
        pass
    from app.constants import DEFAULT_SITE_NAME
    return app.config.get('SITE_NAME', DEFAULT_SITE_NAME)


def _register_error_handlers(app):
    from flask import render_template

    error_pages = {
        403: ('无访问权限', '您没有权限访问此页面'),
        404: ('页面不存在', '您请求的页面未找到'),
        500: ('服务器内部错误', '请稍后重试，或联系系统管理员'),
    }

    for code, (title, message) in error_pages.items():
        app.register_error_handler(
            code,
            lambda e, c=code, t=title, m=message: (
                render_template('errors/error.html', error_code=c, error_title=t, error_message=m), c
            ),
        )
