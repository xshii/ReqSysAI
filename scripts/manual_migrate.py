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
    "ALTER TABLE requirements ADD COLUMN estimate_days FLOAT",
    "ALTER TABLE requirements ADD COLUMN due_date DATE",
    "ALTER TABLE requirements ADD COLUMN parent_id INTEGER REFERENCES requirements(id)",
    # incentives 表新增字段
    "ALTER TABLE incentives ADD COLUMN amount_detail VARCHAR(200)",
    "ALTER TABLE incentives ADD COLUMN gift_status VARCHAR(20)",
    "ALTER TABLE incentives ADD COLUMN gift_item_id INTEGER",
    "ALTER TABLE incentives ADD COLUMN gift_selected_at DATETIME",
    "ALTER TABLE incentives ADD COLUMN gift_notified_at DATETIME",
    "ALTER TABLE incentives ADD COLUMN gift_expires_at DATETIME",
    "ALTER TABLE incentives ADD COLUMN gift_notify_count INTEGER DEFAULT 0",
    "ALTER TABLE incentives ADD COLUMN source VARCHAR(30) DEFAULT 'instant'",
    "ALTER TABLE incentives ADD COLUMN photo VARCHAR(300)",
    "ALTER TABLE incentives ADD COLUMN team_name VARCHAR(100)",
    "ALTER TABLE incentives ADD COLUMN external_nominees VARCHAR(500)",
    "ALTER TABLE incentives ADD COLUMN status VARCHAR(20) DEFAULT 'submitted'",
    "ALTER TABLE incentives ADD COLUMN review_comment VARCHAR(150)",
    "ALTER TABLE incentives ADD COLUMN amount FLOAT",
    "ALTER TABLE incentives ADD COLUMN fund_id INTEGER REFERENCES incentive_funds(id)",
    "ALTER TABLE incentives ADD COLUMN reviewed_by INTEGER REFERENCES users(id)",
    "ALTER TABLE incentives ADD COLUMN reviewed_at DATETIME",
    "ALTER TABLE incentives ADD COLUMN is_public BOOLEAN DEFAULT 1",
    "ALTER TABLE incentives ADD COLUMN likes INTEGER DEFAULT 0",
    # users 表新增字段
    "ALTER TABLE users ADD COLUMN team_view_mode VARCHAR(10) DEFAULT 'group'",
    "ALTER TABLE users ADD COLUMN avatar VARCHAR(300)",
    "ALTER TABLE users ADD COLUMN pinyin VARCHAR(100)",
    "ALTER TABLE users ADD COLUMN manager VARCHAR(100)",
    "ALTER TABLE users ADD COLUMN domain VARCHAR(100)",
    "ALTER TABLE users ADD COLUMN email VARCHAR(200)",
    "ALTER TABLE users ADD COLUMN only_my_group BOOLEAN DEFAULT 1",
    "ALTER TABLE users ADD COLUMN pomodoro_minutes INTEGER DEFAULT 45",
    # permission_applications 补字段
    "ALTER TABLE permission_applications ADD COLUMN applicant_eid VARCHAR(30)",
    # permission_items 补字段
    "ALTER TABLE permission_items ADD COLUMN created_by INTEGER REFERENCES users(id)",
    # external_requests 补字段（建表后新增）
    "ALTER TABLE external_requests ADD COLUMN urgency VARCHAR(20) DEFAULT 'week'",
    # risks 表新增字段
    "ALTER TABLE risks ADD COLUMN owner_id INTEGER REFERENCES users(id)",
    "ALTER TABLE risks ADD COLUMN tracker_name VARCHAR(100)",
    "ALTER TABLE risks ADD COLUMN domain VARCHAR(100)",
    "ALTER TABLE risks ADD COLUMN requirement_id INTEGER REFERENCES requirements(id)",
    "ALTER TABLE risks ADD COLUMN meeting_id INTEGER REFERENCES meetings(id)",
    "ALTER TABLE risks ADD COLUMN aar_id INTEGER REFERENCES aars(id)",
    "ALTER TABLE risks ADD COLUMN resolved_at DATETIME",
    "ALTER TABLE risks ADD COLUMN owner_since DATETIME",
    "ALTER TABLE risks ADD COLUMN deleted_at DATETIME",
    "ALTER TABLE risks ADD COLUMN deleted_by INTEGER REFERENCES users(id)",
]

# 状态简化迁移：旧状态 → 新状态
STATUS_MIGRATION = [
    "UPDATE requirements SET status='pending' WHERE status='pending_review'",
    "UPDATE requirements SET status='pending' WHERE status='pending_dev'",
    "UPDATE requirements SET status='in_progress' WHERE status='in_dev'",
    "UPDATE requirements SET status='in_progress' WHERE status='in_test'",
    # 清理风险域名空格
    "UPDATE risks SET domain=TRIM(domain) WHERE domain IS NOT NULL AND domain != TRIM(domain)",
    # AAR status 'open' → 'draft'（建表默认值与模型不一致的修正）
    "UPDATE aars SET status='draft' WHERE status='open'",
]

# 需要补齐的 CREATE TABLE 语句
CREATE_STATEMENTS = [
    # ---- 核心表（初始建库可能遗漏） ----
    # 角色表
    """CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY,
        name VARCHAR(50) UNIQUE NOT NULL,
        description VARCHAR(200)
    )""",
    # 分组表
    """CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY,
        name VARCHAR(50) UNIQUE NOT NULL,
        is_hidden BOOLEAN DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 项目表
    """CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        status VARCHAR(20) DEFAULT 'active',
        is_hidden BOOLEAN DEFAULT 0,
        parent_id INTEGER REFERENCES projects(id),
        owner_id INTEGER REFERENCES users(id),
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 里程碑表
    """CREATE TABLE IF NOT EXISTS milestones (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        name VARCHAR(200) NOT NULL,
        due_date DATE,
        status VARCHAR(20) DEFAULT 'active',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 风险表
    """CREATE TABLE IF NOT EXISTS risks (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        title VARCHAR(300) NOT NULL,
        description TEXT,
        severity VARCHAR(20) DEFAULT 'medium',
        status VARCHAR(20) DEFAULT 'open',
        owner VARCHAR(100),
        owner_id INTEGER REFERENCES users(id),
        tracker_id INTEGER REFERENCES users(id),
        tracker_name VARCHAR(100),
        domain VARCHAR(100),
        requirement_id INTEGER REFERENCES requirements(id),
        meeting_id INTEGER REFERENCES meetings(id),
        aar_id INTEGER REFERENCES aars(id),
        due_date DATE NOT NULL,
        resolution TEXT,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolved_at DATETIME,
        owner_since DATETIME,
        deleted_at DATETIME,
        deleted_by INTEGER REFERENCES users(id)
    )""",
    # 风险评论
    """CREATE TABLE IF NOT EXISTS risk_comments (
        id INTEGER PRIMARY KEY,
        risk_id INTEGER NOT NULL REFERENCES risks(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        content VARCHAR(500) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 风险审计日志
    """CREATE TABLE IF NOT EXISTS risk_audit_logs (
        id INTEGER PRIMARY KEY,
        risk_id INTEGER NOT NULL REFERENCES risks(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        action VARCHAR(20) NOT NULL,
        detail VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # Todo 表
    """CREATE TABLE IF NOT EXISTS todos (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        title VARCHAR(300) NOT NULL,
        status VARCHAR(20) DEFAULT 'todo',
        category VARCHAR(20) DEFAULT 'work',
        source VARCHAR(20) DEFAULT 'manual',
        parent_id INTEGER REFERENCES todos(id),
        sort_order INTEGER DEFAULT 0,
        due_date DATE,
        created_date DATE,
        done_date DATE,
        need_help BOOLEAN DEFAULT 0,
        blocked_reason VARCHAR(200),
        started_at DATETIME,
        actual_minutes INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # Todo 子项（checklist）
    """CREATE TABLE IF NOT EXISTS todo_items (
        id INTEGER PRIMARY KEY,
        todo_id INTEGER NOT NULL REFERENCES todos(id),
        title VARCHAR(300) NOT NULL,
        is_done BOOLEAN DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 番茄钟
    """CREATE TABLE IF NOT EXISTS pomodoro_sessions (
        id INTEGER PRIMARY KEY,
        todo_id INTEGER NOT NULL REFERENCES todos(id),
        started_at DATETIME,
        minutes INTEGER NOT NULL DEFAULT 0,
        completed BOOLEAN DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 需求评论
    """CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY,
        requirement_id INTEGER NOT NULL REFERENCES requirements(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        content TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 需求活动日志
    """CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY,
        requirement_id INTEGER NOT NULL REFERENCES requirements(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        action VARCHAR(50) NOT NULL,
        detail VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 通知
    """CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        type VARCHAR(30) NOT NULL,
        title VARCHAR(300) NOT NULL,
        link VARCHAR(500),
        is_read BOOLEAN DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # ---- 扩展表 ----
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
        applicant_eid VARCHAR(30),
        reason VARCHAR(300),
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
    # 礼品库表
    """CREATE TABLE IF NOT EXISTS gift_items (
        id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description VARCHAR(500),
        link VARCHAR(500),
        image VARCHAR(300),
        price FLOAT,
        picks INTEGER DEFAULT 0,
        is_active BOOLEAN DEFAULT 1,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 礼品领取记录表
    """CREATE TABLE IF NOT EXISTS gift_records (
        id INTEGER PRIMARY KEY,
        incentive_id INTEGER NOT NULL REFERENCES incentives(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        gift_item_id INTEGER REFERENCES gift_items(id),
        status VARCHAR(20) DEFAULT 'pending',
        notified_at DATETIME,
        expires_at DATETIME,
        selected_at DATETIME,
        purchased_at DATETIME,
        notify_count INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 活动计时器表
    """CREATE TABLE IF NOT EXISTS activity_timers (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        activity VARCHAR(30) NOT NULL,
        label VARCHAR(50) NOT NULL,
        started_at DATETIME NOT NULL,
        minutes INTEGER NOT NULL DEFAULT 0,
        date DATE NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 情绪预测记录
    """CREATE TABLE IF NOT EXISTS emotion_records (
        id INTEGER PRIMARY KEY,
        scan_date DATE NOT NULL,
        member_name VARCHAR(100) NOT NULL,
        "group" VARCHAR(50),
        status VARCHAR(20) NOT NULL,
        risk_level VARCHAR(10) NOT NULL,
        signals TEXT,
        suggestion TEXT,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 情绪评论/跟进
    """CREATE TABLE IF NOT EXISTS emotion_comments (
        id INTEGER PRIMARY KEY,
        record_id INTEGER NOT NULL REFERENCES emotion_records(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        content VARCHAR(500) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 会议记录
    """CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        title VARCHAR(200) NOT NULL,
        date DATE,
        attendees TEXT,
        cc TEXT,
        content TEXT,
        ai_result TEXT,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 周报
    """CREATE TABLE IF NOT EXISTS weekly_reports (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        week_start DATE NOT NULL,
        week_end DATE NOT NULL,
        summary TEXT,
        risks_json TEXT,
        plan_json TEXT,
        content_html TEXT,
        is_frozen BOOLEAN DEFAULT 0,
        frozen_by INTEGER REFERENCES users(id),
        frozen_at DATETIME,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME
    )""",
    # 个人周报
    """CREATE TABLE IF NOT EXISTS personal_weeklies (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        week_start DATE NOT NULL,
        week_end DATE NOT NULL,
        ai_html TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME
    )""",
    # 站会记录
    """CREATE TABLE IF NOT EXISTS standup_records (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        date DATE NOT NULL,
        yesterday_done TEXT,
        today_plan TEXT,
        blocker TEXT,
        has_blocker BOOLEAN DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME
    )""",
    # 知识库
    """CREATE TABLE IF NOT EXISTS knowledges (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        title VARCHAR(200) NOT NULL,
        link_type VARCHAR(30),
        biz_category VARCHAR(50),
        link VARCHAR(500),
        is_pinned BOOLEAN DEFAULT 0,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME
    )""",
    # AAR 复盘
    """CREATE TABLE IF NOT EXISTS aars (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        title VARCHAR(200) NOT NULL,
        trigger VARCHAR(50),
        trigger_ref VARCHAR(200),
        date DATE,
        participants TEXT,
        goal TEXT,
        result TEXT,
        analysis TEXT,
        action TEXT,
        status VARCHAR(20) DEFAULT 'draft',
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME
    )""",
    # 循环 Todo
    """CREATE TABLE IF NOT EXISTS recurring_todos (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        title VARCHAR(500) NOT NULL,
        cycle VARCHAR(20) NOT NULL,
        weekdays VARCHAR(20),
        monthly_day INTEGER,
        monthly_days VARCHAR(50),
        is_active BOOLEAN DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 循环 Todo 完成记录
    """CREATE TABLE IF NOT EXISTS recurring_completions (
        id INTEGER PRIMARY KEY,
        recurring_id INTEGER NOT NULL REFERENCES recurring_todos(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        completed_date DATE NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 审计日志
    """CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY,
        user_id INTEGER REFERENCES users(id),
        action VARCHAR(50) NOT NULL,
        entity_type VARCHAR(50),
        entity_id INTEGER,
        entity_title VARCHAR(200),
        detail TEXT,
        ip_address VARCHAR(45),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 树洞
    """CREATE TABLE IF NOT EXISTS rants (
        id INTEGER PRIMARY KEY,
        alias VARCHAR(50),
        content TEXT NOT NULL,
        likes INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # AI 解析日志
    """CREATE TABLE IF NOT EXISTS ai_parse_logs (
        id INTEGER PRIMARY KEY,
        input_type VARCHAR(50),
        raw_input TEXT,
        ai_output TEXT,
        created_by INTEGER REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 邮件设置
    """CREATE TABLE IF NOT EXISTS email_settings (
        id INTEGER PRIMARY KEY,
        entity_type VARCHAR(50) NOT NULL,
        entity_id INTEGER NOT NULL,
        subject VARCHAR(300),
        to_list TEXT,
        cc_list TEXT,
        updated_by INTEGER REFERENCES users(id),
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # IP 变更申请
    """CREATE TABLE IF NOT EXISTS ip_change_requests (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        old_ip VARCHAR(45),
        new_ip VARCHAR(45) NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        reviewed_by INTEGER REFERENCES users(id),
        reviewed_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 里程碑模版
    """CREATE TABLE IF NOT EXISTS milestone_templates (
        id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 里程碑模版子项
    """CREATE TABLE IF NOT EXISTS milestone_template_items (
        id INTEGER PRIMARY KEY,
        template_id INTEGER NOT NULL REFERENCES milestone_templates(id),
        name VARCHAR(200) NOT NULL,
        offset_days INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0
    )""",
    # 激励报告
    """CREATE TABLE IF NOT EXISTS incentive_reports (
        id INTEGER PRIMARY KEY,
        period VARCHAR(50),
        data TEXT,
        created_by INTEGER REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 激励基金
    """CREATE TABLE IF NOT EXISTS incentive_funds (
        id INTEGER PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        source VARCHAR(100),
        total_amount FLOAT DEFAULT 0,
        expires_at DATE,
        note TEXT,
        created_by INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # ---- 关联表 ----
    """CREATE TABLE IF NOT EXISTS user_roles (
        user_id INTEGER NOT NULL REFERENCES users(id),
        role_id INTEGER NOT NULL REFERENCES roles(id),
        PRIMARY KEY (user_id, role_id)
    )""",
    """CREATE TABLE IF NOT EXISTS user_followed_projects (
        user_id INTEGER NOT NULL REFERENCES users(id),
        project_id INTEGER NOT NULL REFERENCES projects(id),
        PRIMARY KEY (user_id, project_id)
    )""",
    """CREATE TABLE IF NOT EXISTS requirement_dependencies (
        from_id INTEGER NOT NULL REFERENCES requirements(id),
        to_id INTEGER NOT NULL REFERENCES requirements(id),
        PRIMARY KEY (from_id, to_id)
    )""",
    """CREATE TABLE IF NOT EXISTS todo_requirements (
        todo_id INTEGER NOT NULL REFERENCES todos(id),
        requirement_id INTEGER NOT NULL REFERENCES requirements(id),
        PRIMARY KEY (todo_id, requirement_id)
    )""",
    """CREATE TABLE IF NOT EXISTS incentive_nominees (
        incentive_id INTEGER NOT NULL REFERENCES incentives(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        PRIMARY KEY (incentive_id, user_id)
    )""",
    # 权限申请（批量）
    """CREATE TABLE IF NOT EXISTS permission_requests (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        category VARCHAR(100),
        resource VARCHAR(200) NOT NULL,
        repo_path VARCHAR(300),
        description VARCHAR(300),
        applicants TEXT,
        submitter_id INTEGER NOT NULL REFERENCES users(id),
        status VARCHAR(20) DEFAULT 'draft',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        submitted_at DATETIME,
        approved_at DATETIME,
        updated_at DATETIME
    )""",
    # 外部诉求
    """CREATE TABLE IF NOT EXISTS external_requests (
        id INTEGER PRIMARY KEY,
        target_user_id INTEGER NOT NULL REFERENCES users(id),
        name VARCHAR(100),
        contact VARCHAR(200),
        title VARCHAR(300) NOT NULL,
        description TEXT,
        urgency VARCHAR(20) DEFAULT 'week',
        status VARCHAR(20) DEFAULT 'pending',
        response TEXT,
        assigned_id INTEGER REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    # 喝水记录
    """CREATE TABLE IF NOT EXISTS water_logs (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        ml INTEGER NOT NULL,
        date DATE NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
]


INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_todos_user_id ON todos(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_requirements_project_id ON requirements(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_requirements_assignee_id ON requirements(assignee_id)",
    "CREATE INDEX IF NOT EXISTS ix_requirements_parent_id ON requirements(parent_id)",
    "CREATE INDEX IF NOT EXISTS ix_requirements_number ON requirements(number)",
    "CREATE INDEX IF NOT EXISTS ix_risks_owner_id ON risks(owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_risks_tracker_id ON risks(tracker_id)",
    "CREATE INDEX IF NOT EXISTS ix_risks_project_id ON risks(project_id)",
    "CREATE INDEX IF NOT EXISTS ix_pomodoro_sessions_todo_id ON pomodoro_sessions(todo_id)",
    "CREATE INDEX IF NOT EXISTS ix_users_employee_id ON users(employee_id)",
    "CREATE INDEX IF NOT EXISTS ix_users_ip_address ON users(ip_address)",
    "CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id)",
]

UNIQUE_CONSTRAINTS = [
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_standup_user_date ON standup_records(user_id, date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_week ON weekly_reports(project_id, week_start)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_personal_week ON personal_weeklies(user_id, week_start)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_email_setting_entity ON email_settings(entity_type, entity_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_recurring_completion ON recurring_completions(recurring_id, user_id, completed_date)",
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

        # 执行索引语句
        for sql in INDEX_STATEMENTS:
            idx_name = sql.split('IF NOT EXISTS')[1].split('ON')[0].strip()
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
                print(f'  ✓ 索引 {idx_name} 创建成功')
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e).lower():
                    print(f'  - 索引 {idx_name} 已存在，跳过')
                else:
                    print(f'  ! 索引 {idx_name} 失败: {e}')

        # 执行唯一约束
        for sql in UNIQUE_CONSTRAINTS:
            idx_name = sql.split('IF NOT EXISTS')[1].split('ON')[0].strip()
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
                print(f'  ✓ 唯一约束 {idx_name} 创建成功')
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e).lower():
                    print(f'  - 唯一约束 {idx_name} 已存在，跳过')
                else:
                    print(f'  ! 唯一约束 {idx_name} 失败: {e}')

        # 执行状态迁移
        for sql in STATUS_MIGRATION:
            try:
                result = db.session.execute(db.text(sql))
                db.session.commit()
                rows = result.rowcount
                if rows > 0:
                    print(f'  ✓ 状态迁移: {sql.split("=")[1].split("WHERE")[0].strip()} ← {rows} 行')
                else:
                    print(f'  - 状态迁移: 无需更新')
            except Exception as e:
                db.session.rollback()
                print(f'  ! 状态迁移失败: {e}')

        print('\n✅ 数据库补齐完成！')


if __name__ == '__main__':
    run()
