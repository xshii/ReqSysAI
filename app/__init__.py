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

    # Register error handlers
    _register_error_handlers(app)

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
