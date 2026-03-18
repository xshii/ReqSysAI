"""Idempotent seed: creates roles and default admin user if they don't exist."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.user import Role, User


def seed():
    app = create_app()
    with app.app_context():
        roles_data = [
            ('employee', '员工', '普通研发人员'),
            ('pm', '项目经理', '项目管理和需求审批'),
            ('executive', '高层领导', '查看汇总报表'),
            ('admin', '系统管理员', '系统配置和用户管理'),
        ]
        for name, display, desc in roles_data:
            if not Role.query.filter_by(name=name).first():
                db.session.add(Role(name=name, display_name=display, description=desc))
        db.session.commit()

        if not User.query.filter_by(username='admin').first():
            admin_role = Role.query.filter_by(name='admin').first()
            admin = User(
                username='admin',
                email='admin@company.com',
                display_name='系统管理员',
                role=admin_role,
                auth_type='local',
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('Default admin user created (admin / admin123)')
        else:
            print('Admin user already exists, skipping.')


if __name__ == '__main__':
    seed()
