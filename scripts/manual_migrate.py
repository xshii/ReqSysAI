"""手动补齐数据库字段和表（不依赖 flask db）。
用法: python scripts/manual_migrate.py
已存在的字段/表会自动跳过，可重复执行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

app = create_app()

# 需要补齐的 ALTER TABLE 语句
ALTER_STATEMENTS = [
    # requirements 表新增字段
    "ALTER TABLE requirements ADD COLUMN category VARCHAR(100)",
    "ALTER TABLE requirements ADD COLUMN source VARCHAR(50) DEFAULT 'coding'",
    "ALTER TABLE requirements ADD COLUMN ai_ratio INTEGER",
    "ALTER TABLE requirements ADD COLUMN completion INTEGER DEFAULT 0",
    "ALTER TABLE requirements ADD COLUMN start_date DATE",
    "ALTER TABLE requirements ADD COLUMN assignee_name VARCHAR(100)",
    "ALTER TABLE requirements ADD COLUMN code_lines INTEGER",
    "ALTER TABLE requirements ADD COLUMN test_cases INTEGER",
]

# 需要补齐的 CREATE TABLE 语句
CREATE_STATEMENTS = [
    # 项目成员表
    """CREATE TABLE IF NOT EXISTS project_members (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        user_id INTEGER REFERENCES users(id),
        external_name VARCHAR(100),
        external_eid VARCHAR(30),
        project_role VARCHAR(50) DEFAULT 'DEV',
        is_key BOOLEAN DEFAULT 1,
        expected_ratio INTEGER,
        sort_order INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 权限目录表
    """CREATE TABLE IF NOT EXISTS permission_items (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        category VARCHAR(100),
        resource VARCHAR(200) NOT NULL,
        repo_path VARCHAR(300),
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 权限申请表
    """CREATE TABLE IF NOT EXISTS permission_applications (
        id INTEGER PRIMARY KEY,
        item_id INTEGER NOT NULL REFERENCES permission_items(id),
        applicant_name TEXT NOT NULL,
        reason TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        is_frozen BOOLEAN DEFAULT 0,
        submitted_by INTEGER NOT NULL REFERENCES users(id),
        approved_by INTEGER REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        approved_at DATETIME
    )""",
    # 站点设置表（甘特图状态等）
    """CREATE TABLE IF NOT EXISTS site_settings (
        id INTEGER PRIMARY KEY,
        key VARCHAR(100) UNIQUE NOT NULL,
        value TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
]


def run():
    with app.app_context():
        # 执行建表语句
        for sql in CREATE_STATEMENTS:
            table_name = sql.split('IF NOT EXISTS')[1].split('(')[0].strip()
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
                print(f'  ✓ 创建表 {table_name}')
            except Exception:
                db.session.rollback()
                print(f'  - 表 {table_name} 已存在，跳过')

        # 执行加字段语句
        for sql in ALTER_STATEMENTS:
            parts = sql.split()
            table = parts[2]
            col = parts[5]
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
                print(f'  ✓ {table}.{col} 添加成功')
            except Exception as e:
                db.session.rollback()
                if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f'  - {table}.{col} 已存在，跳过')
                else:
                    print(f'  ! {table}.{col} 失败: {e}')

        print('\n✅ 数据库补齐完成！')
        print('接下来执行: flask db stamp head')


if __name__ == '__main__':
    run()
