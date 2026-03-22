import os

from flask import Flask

from config import config


def create_app(config_name=None):
    app = Flask(__name__)
    config_name = config_name or os.getenv('FLASK_ENV', 'development')
    app.config.from_object(config[config_name])

    # Initialize extensions
    from app.extensions import db, migrate, login_manager, csrf
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    app.config['WTF_CSRF_ENABLED'] = False  # Internal app, IP-based auth

    # Import models so they are registered with SQLAlchemy
    from app import models  # noqa: F401

    # Register blueprints
    from app.auth import auth_bp
    from app.main import main_bp
    from app.admin import admin_bp
    from app.project import project_bp
    from app.requirement import requirement_bp
    from app.ai import ai_bp
    from app.todo import todo_bp
    from app.dashboard import dashboard_bp
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

    # Full-text search index
    from app.services.search import init_fts
    init_fts(app)

    # Template filters
    import json as _json
    app.jinja_env.filters['from_json'] = lambda s: _json.loads(s) if s else []

    # Inject sidebar groups into all templates
    @app.context_processor
    def inject_sidebar_groups():
        from flask_login import current_user
        from flask import request as req
        if current_user.is_authenticated:
            from app.models.user import User, Group
            from app.models.project import Project
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
            all_projects = Project.query.filter_by(status='active').order_by(Project.name).all()
            followed_ids = set(p.id for p in current_user.followed_projects.all())
            # Followed projects first, then others
            followed = [p for p in all_projects if p.id in followed_ids]
            unfollowed = [p for p in all_projects if p.id not in followed_ids]
            projects = followed + unfollowed

            # Notification counts for navbar bell
            from app.models.risk import Risk
            from app.models.requirement import Requirement
            from datetime import date
            today = date.today()
            notif_risks = Risk.query.filter(
                Risk.status == 'open',
                db.or_(Risk.tracker_id == current_user.id, Risk.created_by == current_user.id),
                Risk.due_date <= today,
            ).count()
            notif_overdue_reqs = Requirement.query.filter(
                Requirement.assignee_id == current_user.id,
                Requirement.status.notin_(('done', 'closed')),
                Requirement.due_date < today,
            ).count()
            notif_count = notif_risks + notif_overdue_reqs
            if current_user.is_team_manager:
                from app.models.incentive import Incentive
                notif_count += Incentive.query.filter_by(status='pending').count()
            if current_user.is_admin:
                from app.models.ip_request import IPChangeRequest
                notif_count += IPChangeRequest.query.filter_by(status='pending').count()
            # Help todos assigned to me (someone asked me for help)
            from app.models.todo import Todo
            notif_help = Todo.query.filter(
                Todo.user_id == current_user.id,
                Todo.parent_id.isnot(None),
                Todo.status == 'todo',
            ).count()
            notif_count += notif_help

            return dict(sidebar_groups=groups, sidebar_cur_group=cur_group,
                        sidebar_projects=projects, sidebar_followed_ids=followed_ids,
                        notif_count=notif_count,
                        ai_enabled=app.config.get('AI_ENABLED', True))
        return dict(sidebar_groups=[], sidebar_cur_group='', sidebar_projects=[],
                    sidebar_followed_ids=set(), notif_count=0)

    return app


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
