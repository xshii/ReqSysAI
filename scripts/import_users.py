"""Import users from CSV file.

CSV format (with header):
姓名,工号,小组,角色

Example:
姓名,工号,小组,角色
张三,a00123456,研发一组,DE
李四,b00234567,研发二组,SE;QA

Notes:
- 角色支持多个，用分号(;)分隔
- 已存在的工号会更新姓名、小组、角色（追加，不覆盖隐藏角色）
- 新工号会创建用户，IP 留空占位(需首次登录时绑定)
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.user import Role, User
from app.utils.pinyin import to_pinyin


def import_csv(filepath):
    app = create_app()
    with app.app_context():
        hidden = set(app.config.get('HIDDEN_ROLES', []) + ['Admin'])

        with open(filepath, encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            created, updated, skipped = 0, 0, 0

            for row in reader:
                name = (row.get('姓名') or '').strip()
                eid = (row.get('工号') or '').strip().lower()
                group = (row.get('小组') or '').strip() or None
                role_str = (row.get('角色') or '').strip()

                if not name or not eid:
                    print(f'  SKIP: empty name/eid -> {row}')
                    skipped += 1
                    continue

                # Parse roles (semicolon separated)
                role_names = [r.strip() for r in role_str.replace(',', ';').split(';') if r.strip()]
                # Filter out hidden roles from CSV input
                role_names = [r for r in role_names if r not in hidden]
                roles = Role.query.filter(Role.name.in_(role_names)).all() if role_names else []
                if role_names and len(roles) != len(role_names):
                    found = {r.name for r in roles}
                    missing = set(role_names) - found
                    print(f'  WARN: {eid} unknown roles: {missing}')

                user = User.query.filter_by(employee_id=eid).first()
                if user:
                    user.name = name
                    user.pinyin = to_pinyin(name)
                    user.group = group
                    # Keep hidden roles, replace visible ones
                    kept = [r for r in user.roles if r.name in hidden]
                    user.roles = kept + roles
                    updated += 1
                    print(f'  UPDATE: {eid} {name} -> {group} [{",".join(r.name for r in user.roles)}]')
                else:
                    # New user - placeholder IP, will be bound on first login
                    placeholder_ip = f'pending-{eid}'
                    user = User(
                        employee_id=eid,
                        name=name,
                        pinyin=to_pinyin(name),
                        ip_address=placeholder_ip,
                        group=group,
                        roles=roles,
                    )
                    db.session.add(user)
                    created += 1
                    print(f'  CREATE: {eid} {name} -> {group} [{",".join(r.name for r in roles)}]')

            db.session.commit()
            print(f'\nDone: {created} created, {updated} updated, {skipped} skipped')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python scripts/import_users.py <path-to-csv>')
        print('CSV header: 姓名,工号,小组,角色')
        sys.exit(1)
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f'File not found: {filepath}')
        sys.exit(1)
    print(f'Importing from {filepath} ...')
    import_csv(filepath)
