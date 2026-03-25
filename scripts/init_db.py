"""Idempotent seed: creates roles and default admin from config.yml."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.user import Role, User
from app.utils.pinyin import to_pinyin


def seed():
    flask_app = create_app()

    # Step 1: create tables
    with flask_app.app_context():
        import app.models.notification  # noqa
        import app.models.audit  # noqa
        db.create_all()
        from sqlalchemy import text
        for sql in [
            'CREATE INDEX IF NOT EXISTS idx_req_title ON requirements(title)',
            'CREATE INDEX IF NOT EXISTS idx_todo_title ON todos(title)',
            'CREATE INDEX IF NOT EXISTS idx_meeting_title ON meetings(title)',
            'CREATE INDEX IF NOT EXISTS idx_risk_title ON risks(title)',
            'CREATE INDEX IF NOT EXISTS idx_user_name ON users(name)',
            'CREATE INDEX IF NOT EXISTS idx_aar_title ON aars(title)',
        ]:
            try:
                db.session.execute(text(sql))
            except Exception:  # noqa: S110
                pass
        db.session.commit()

    # Step 2: seed data (fresh session)
    with flask_app.app_context():
        # Roles
        for r in flask_app.config.get('ROLES', []):
            name = r['name']
            if not Role.query.filter_by(name=name).first():
                db.session.add(Role(name=name, description=r.get('desc', '')))
        db.session.commit()
        print(f'Roles: {Role.query.count()}')

        # Milestone templates
        from app.constants import MILESTONE_TEMPLATES, resolve_template_offsets
        from app.models.project import MilestoneTemplate, MilestoneTemplateItem
        if MilestoneTemplate.query.count() == 0:
            for tpl in MILESTONE_TEMPLATES:
                t = MilestoneTemplate(name=tpl['name'], description=tpl['description'])
                resolved = resolve_template_offsets(tpl['items'])
                for i, (iname, offset) in enumerate(resolved):
                    t.items.append(MilestoneTemplateItem(name=iname, offset_days=offset, sort_order=i))
                db.session.add(t)
            db.session.commit()
            print(f'Milestone templates: {MilestoneTemplate.query.count()}')

        # Default admin
        admin_cfg = flask_app.config.get('ADMIN_CONFIG', {})
        eid = admin_cfg.get('employee_id', 'a00000001')
        if not User.query.filter_by(employee_id=eid).first():
            admin_role = Role.query.filter_by(name='Admin').first()
            admin_name = admin_cfg.get('name', '管理员')
            admin = User(
                employee_id=eid,
                name=admin_name,
                pinyin=to_pinyin(admin_name),
                ip_address=admin_cfg.get('ip', ''),
                manager='周明 z00880001',
                roles=[admin_role] if admin_role else [],
            )
            db.session.add(admin)
            db.session.commit()
            print(f'Default admin created (employee_id={eid})')
        else:
            print('Admin user already exists, skipping.')


if __name__ == '__main__':
    seed()
