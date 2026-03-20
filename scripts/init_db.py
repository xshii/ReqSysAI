"""Idempotent seed: creates roles and default admin from config.yml."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.user import Role, User
from app.utils.pinyin import to_pinyin


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()

        # Sync roles from config.yml
        for r in app.config.get('ROLES', []):
            name = r['name']
            existing = Role.query.filter_by(name=name).first()
            if existing:
                existing.description = r.get('desc', '')
            else:
                db.session.add(Role(name=name, description=r.get('desc', '')))
        db.session.commit()

        # Default admin
        admin_cfg = app.config.get('ADMIN_CONFIG', {})
        eid = admin_cfg.get('employee_id', 'a00000001')
        if not User.query.filter_by(employee_id=eid).first():
            admin_role = Role.query.filter_by(name='Admin').first()
            admin_name = admin_cfg.get('name', '管理员')
            admin = User(
                employee_id=eid,
                name=admin_name,
                pinyin=to_pinyin(admin_name),
                ip_address=admin_cfg.get('ip', '127.0.0.1'),
                roles=[admin_role],
            )
            db.session.add(admin)
            db.session.commit()
            print(f'Default admin created (employee_id={eid})')
        else:
            print('Admin user already exists, skipping.')


if __name__ == '__main__':
    seed()
