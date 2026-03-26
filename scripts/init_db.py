"""Idempotent seed: creates tables, roles, admin, and optional rich test data."""
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.user import Role, User
from app.utils.pinyin import to_pinyin


def seed():
    flask_app = create_app()

    # Step 1: create tables & indexes
    with flask_app.app_context():
        # Import ALL models so db.create_all() creates all tables
        import app.models.activity_timer  # noqa
        import app.models.ai_log  # noqa
        import app.models.audit  # noqa
        import app.models.email_setting  # noqa
        import app.models.emotion  # noqa
        import app.models.incentive  # noqa
        import app.models.ip_request  # noqa
        import app.models.knowledge  # noqa
        import app.models.meeting  # noqa
        import app.models.notification  # noqa
        import app.models.project  # noqa
        import app.models.project_member  # noqa
        import app.models.rant  # noqa
        import app.models.recurring_completion  # noqa
        import app.models.recurring_todo  # noqa
        import app.models.report  # noqa
        import app.models.requirement  # noqa
        import app.models.risk  # noqa
        import app.models.site_setting  # noqa
        import app.models.standup  # noqa
        import app.models.todo  # noqa
        import app.models.user  # noqa

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

    # Step 2: seed roles + milestone templates + admin
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
                group='研发一组',
                roles=[admin_role] if admin_role else [],
            )
            db.session.add(admin)
            db.session.commit()
            print(f'Default admin created (employee_id={eid})')
        else:
            print('Admin user already exists, skipping.')

        # Default hidden project: 团队管理
        from app.models.project import Project
        admin_user = User.query.filter_by(employee_id=eid).first()
        if admin_user and not Project.query.filter_by(name='团队管理').first():
            db.session.add(Project(
                name='团队管理',
                description='内部团队绩效与人员管理（仅管理层可见）',
                status='active', is_hidden=True,
                owner_id=admin_user.id, created_by=admin_user.id,
            ))
            db.session.commit()
            print('Default hidden project "团队管理" created.')
        else:
            print('Hidden project "团队管理" already exists, skipping.')


def seed_test_data():
    """Create rich test data for development / demo purposes."""
    flask_app = create_app()

    with flask_app.app_context():
        # Skip if test data already exists
        if User.query.count() > 1:
            print('Test data already exists, skipping. Delete the DB to regenerate.')
            return

        from app.models.incentive import Incentive, IncentiveFund
        from app.models.knowledge import AAR, Knowledge, PermissionApplication, PermissionItem
        from app.models.meeting import Meeting
        from app.models.project import Milestone, Project
        from app.models.project_member import ProjectMember
        from app.models.requirement import Activity, Comment, Requirement
        from app.models.risk import Risk, RiskComment
        from app.models.standup import StandupRecord
        from app.models.recurring_todo import RecurringTodo
        from app.models.todo import PomodoroSession, Todo, TodoItem

        now = datetime.now(timezone.utc)
        today = date.today()

        # ── Roles lookup ──
        role_de = Role.query.filter_by(name='DE').first()
        role_pm = Role.query.filter_by(name='PM').first()
        role_qa = Role.query.filter_by(name='QA').first()
        role_pl = Role.query.filter_by(name='PL').first()
        role_se = Role.query.filter_by(name='SE').first()
        role_te = Role.query.filter_by(name='TE').first()
        role_fo = Role.query.filter_by(name='FO').first()
        admin = User.query.filter_by(employee_id='a00000001').first()

        # ── Groups ──
        from app.models.user import Group as UserGroup
        for gname in ['研发一组', '研发二组']:
            if not UserGroup.query.filter_by(name=gname).first():
                db.session.add(UserGroup(name=gname, is_hidden=False))
        db.session.flush()
        print('Created groups')

        # ── Users ──
        users_data = [
            ('z00880001', '周明', '192.168.3.10', '赵总 a00000001', '平台架构', [role_pl]),
            ('l00880002', '李婷', '192.168.3.11', '周明 z00880001', '需求管理', [role_pm]),
            ('w00880003', '王磊', '192.168.3.12', '周明 z00880001', '后端开发', [role_de]),
            ('c00880004', '陈晓', '192.168.3.13', '周明 z00880001', '后端开发', [role_de]),
            ('z00880005', '张伟', '192.168.3.14', '周明 z00880001', '前端开发', [role_de]),
            ('h00880006', '黄丽', '192.168.3.15', '周明 z00880001', '测试', [role_te]),
            ('l00880007', '刘洋', '192.168.3.16', '周明 z00880001', 'AI算法', [role_se]),
            ('x00880008', '徐芳', '192.168.3.17', '周明 z00880001', '质量管理', [role_qa]),
            ('s00880009', '孙鹏', '192.168.3.18', '李婷 l00880002', '后端开发', [role_de]),
            ('g00880010', '郭敏', '192.168.3.19', '李婷 l00880002', '前端开发', [role_de]),
            ('m00880011', '马超', '192.168.3.20', '李婷 l00880002', '测试', [role_te]),
            ('y00880012', '杨帆', '192.168.3.21', '周明 z00880001', '产品设计', [role_fo]),
        ]
        users = {}
        for eid, name, ip, mgr, domain, roles in users_data:
            u = User(
                employee_id=eid, name=name, ip_address=ip,
                pinyin=to_pinyin(name), manager=mgr, domain=domain,
                group='研发一组' if int(eid[4:]) % 2 == 1 else '研发二组',
                roles=roles, last_login=now - timedelta(hours=int(eid[-1]) * 3),
            )
            db.session.add(u)
            users[eid] = u
        db.session.flush()
        print(f'Created {len(users)} test users')

        zhou = users['z00880001']
        li = users['l00880002']
        wang = users['w00880003']
        chen = users['c00880004']
        zhang = users['z00880005']
        huang = users['h00880006']
        liu = users['l00880007']
        xu = users['x00880008']
        sun = users['s00880009']
        guo = users['g00880010']
        ma = users['m00880011']
        yang = users['y00880012']

        # ── Projects ──
        proj_main = Project(
            name='智能研发协作平台', description='建设一站式研发管理平台，覆盖需求、任务、风险、周报等全流程',
            status='active', owner_id=zhou.id, created_by=li.id,
            created_at=now - timedelta(days=60),
        )
        proj_ai = Project(
            name='AI辅助模块', description='集成大语言模型实现需求解析、周报生成、会议纪要提取等AI能力',
            status='active', parent=proj_main, owner_id=liu.id, created_by=li.id,
            created_at=now - timedelta(days=45),
        )
        proj_mobile = Project(
            name='移动端适配', description='响应式布局优化，支持手机/平板访问核心功能',
            status='active', parent=proj_main, owner_id=zhang.id, created_by=li.id,
            created_at=now - timedelta(days=30),
        )
        proj_legacy = Project(
            name='旧系统迁移', description='将旧OA系统数据迁移至新平台',
            status='closed', owner_id=wang.id, created_by=li.id,
            created_at=now - timedelta(days=120),
        )
        proj_hidden = Project.query.filter_by(name='团队管理').first()  # already created by seed()
        for p in [proj_main, proj_ai, proj_mobile, proj_legacy]:
            db.session.add(p)
        db.session.flush()
        print(f'Created 4 test projects (+ 团队管理 from seed)')

        # ── Milestones ──
        ms_data = [
            (proj_main, 'Charter 立项', today - timedelta(days=60), 'done'),
            (proj_main, 'TR1 需求评审', today - timedelta(days=40), 'done'),
            (proj_main, 'TR2 方案评审', today - timedelta(days=20), 'done'),
            (proj_main, 'TR4 编码完成', today + timedelta(days=14), 'active'),
            (proj_main, 'TR5 系统测试', today + timedelta(days=28), 'active'),
            (proj_main, 'GA 正式发布', today + timedelta(days=42), 'active'),
            (proj_ai, '算法选型', today - timedelta(days=30), 'done'),
            (proj_ai, '模型集成', today + timedelta(days=7), 'active'),
            (proj_ai, '效果调优', today + timedelta(days=21), 'active'),
            (proj_mobile, '原型设计', today - timedelta(days=10), 'done'),
            (proj_mobile, '核心页面', today + timedelta(days=10), 'active'),
            (proj_mobile, '全量适配', today + timedelta(days=25), 'active'),
        ]
        milestones = {}
        for proj, name, due, status in ms_data:
            ms = Milestone(project_id=proj.id, name=name, due_date=due, status=status)
            db.session.add(ms)
            milestones[name] = ms
        db.session.flush()
        print(f'Created {len(ms_data)} milestones')

        # ── Project Members ──
        members_data = [
            # (project, user, role, is_key, sort_order, expected_ratio)
            (proj_main, li, 'PM', True, 0, 80),
            (proj_main, zhou, '技术负责人', True, 1, 30),
            (proj_main, wang, '后端开发', True, 2, 100),
            (proj_main, chen, '后端开发', True, 3, 100),
            (proj_main, zhang, '前端开发', True, 4, 80),
            (proj_main, huang, '测试', True, 5, 60),
            (proj_main, xu, 'QA', True, 6, 30),
            (proj_main, yang, '产品设计', True, 7, 50),
            (proj_ai, liu, '技术负责人', True, 0, 100),
            (proj_ai, wang, '后端开发', True, 1, 50),
            (proj_ai, li, 'PM', True, 2, 20),
            (proj_mobile, zhang, '前端开发', True, 0, 80),
            (proj_mobile, guo, '前端开发', True, 1, 100),
            (proj_mobile, li, 'PM', True, 2, 20),
            (proj_mobile, yang, '产品设计', True, 3, 40),
            (proj_hidden, admin, 'PM', True, 0, 50),
        ]
        for proj, user, role, is_key, sort, ratio in members_data:
            db.session.add(ProjectMember(
                project_id=proj.id, user_id=user.id, project_role=role,
                is_key=is_key, sort_order=sort, expected_ratio=ratio,
            ))
        db.session.flush()
        print(f'Created {len(members_data)} project members')

        # ── Requirements ──
        req_counter = [0]

        def make_req(proj, title, priority, status, assignee, est_days,
                     start_offset, due_offset, parent=None, source=None, ai_ratio=None):
            req_counter[0] += 1
            r = Requirement(
                number=f'REQ-{req_counter[0]:03d}', project_id=proj.id,
                title=title, priority=priority, status=status,
                assignee_id=assignee.id if assignee else None,
                assignee_name=assignee.name if assignee else None,
                estimate_days=est_days,
                start_date=today + timedelta(days=start_offset) if start_offset is not None else None,
                due_date=today + timedelta(days=due_offset) if due_offset is not None else None,
                parent_id=parent.id if parent else None,
                source=source, ai_ratio=ai_ratio,
                created_by=li.id,
                created_at=now - timedelta(days=max(0, -(start_offset or 0)) + 5),
            )
            db.session.add(r)
            db.session.flush()
            return r

        # Main project requirements
        r1 = make_req(proj_main, '用户登录与IP绑定', 'high', 'done', wang, 5, -30, -25, ai_ratio=20)
        r2 = make_req(proj_main, '项目管理CRUD', 'high', 'done', wang, 8, -25, -17, ai_ratio=35)
        r3 = make_req(proj_main, '需求管理模块', 'high', 'in_dev', chen, 10, -15, 5, ai_ratio=40)
        r3_1 = make_req(proj_main, '需求列表与筛选', 'high', 'done', chen, 3, -15, -12, parent=r3, source='coding', ai_ratio=45)
        r3_2 = make_req(proj_main, '需求详情与编辑', 'high', 'in_dev', chen, 4, -12, -3, parent=r3, source='coding', ai_ratio=50)
        r3_3 = make_req(proj_main, '子需求与关联', 'medium', 'pending_dev', chen, 3, -3, 5, parent=r3, source='coding', ai_ratio=30)
        r4 = make_req(proj_main, 'Todo任务管理', 'high', 'in_dev', zhang, 8, -10, 8, ai_ratio=25)
        r4_1 = make_req(proj_main, '任务拖拽排序', 'medium', 'done', zhang, 2, -10, -8, parent=r4, source='coding', ai_ratio=60)
        r4_2 = make_req(proj_main, '番茄钟计时', 'medium', 'in_dev', zhang, 3, -8, 0, parent=r4, source='coding', ai_ratio=30)
        r4_3 = make_req(proj_main, '周期任务', 'low', 'pending_dev', zhang, 3, 0, 8, parent=r4, source='coding', ai_ratio=20)
        r5 = make_req(proj_main, '风险管理模块', 'high', 'in_test', huang, 6, -20, -5, ai_ratio=15)
        r6 = make_req(proj_main, '周报生成与导出', 'medium', 'in_dev', wang, 5, -5, 10, ai_ratio=55)
        r7 = make_req(proj_main, '权限申请流程', 'medium', 'pending_dev', sun, 4, 5, 15, ai_ratio=30)
        r8 = make_req(proj_main, '统计报表', 'medium', 'pending_dev', guo, 6, 10, 25, ai_ratio=40)
        r9 = make_req(proj_main, '激励系统', 'low', 'pending_review', yang, 5, 15, 30, ai_ratio=20)
        # Overdue requirement
        r10 = make_req(proj_main, '数据导入导出', 'high', 'in_dev', sun, 4, -10, -2, ai_ratio=35)

        # AI project requirements
        r_ai1 = make_req(proj_ai, '需求智能解析', 'high', 'in_dev', liu, 8, -20, 5, ai_ratio=80)
        r_ai2 = make_req(proj_ai, '周报AI生成', 'high', 'pending_dev', liu, 6, 0, 14, ai_ratio=90)
        r_ai3 = make_req(proj_ai, '会议纪要提取', 'medium', 'pending_dev', wang, 5, 7, 21, ai_ratio=85)

        # Mobile project requirements
        r_m1 = make_req(proj_mobile, '响应式布局框架', 'high', 'in_dev', zhang, 5, -10, 3, ai_ratio=45)
        r_m2 = make_req(proj_mobile, '移动端Todo页面', 'high', 'pending_dev', guo, 4, 3, 12, ai_ratio=50)
        r_m3 = make_req(proj_mobile, '移动端看板', 'medium', 'pending_dev', guo, 5, 10, 20, ai_ratio=40)

        # Hidden project (团队管理) requirements — assigned to admin
        r_h1 = make_req(proj_hidden, '团队绩效考核体系', 'high', 'in_dev', admin, 8, -15, 10, ai_ratio=30)
        r_h1_1 = make_req(proj_hidden, '绩效指标定义', 'high', 'done', admin, 3, -15, -10, parent=r_h1, source='analysis', ai_ratio=25)
        r_h1_2 = make_req(proj_hidden, '考核流程设计', 'medium', 'in_dev', admin, 3, -10, 0, parent=r_h1, source='analysis', ai_ratio=35)
        r_h1_3 = make_req(proj_hidden, '考核工具开发', 'medium', 'pending_dev', admin, 2, 0, 10, parent=r_h1, source='coding', ai_ratio=40)
        r_h2 = make_req(proj_hidden, '人员培训计划', 'medium', 'pending_dev', admin, 5, 5, 20, ai_ratio=20)

        print(f'Created {req_counter[0]} requirements')

        # ── Requirement Comments & Activities ──
        comments_data = [
            (r3, chen, '已完成列表页，筛选功能明天开始'),
            (r3, li, '优先级建议：先做关键筛选项，高级筛选后续迭代'),
            (r5, huang, '测试用例已覆盖80%，发现2个边界问题'),
            (r5, wang, '边界问题已修复，请复测'),
            (r_ai1, liu, 'Ollama本地模型效果不错，准确率约85%'),
            (r10, sun, '导入功能基本完成，导出还需2天'),
            (r10, li, '这个延期了，请加快进度'),
        ]
        for req, user, content in comments_data:
            db.session.add(Comment(
                requirement_id=req.id, user_id=user.id, content=content,
                created_at=now - timedelta(hours=len(content)),
            ))

        activities_data = [
            (r1, wang, 'status_changed', '状态: pending_dev → in_dev'),
            (r1, wang, 'status_changed', '状态: in_dev → done'),
            (r2, wang, 'status_changed', '状态: pending_dev → done'),
            (r3, chen, 'status_changed', '状态: pending_dev → in_dev'),
            (r5, wang, 'status_changed', '状态: in_dev → in_test'),
            (r10, sun, 'status_changed', '状态: pending_dev → in_dev'),
        ]
        for req, user, action, detail in activities_data:
            db.session.add(Activity(
                requirement_id=req.id, user_id=user.id,
                action=action, detail=detail,
                created_at=now - timedelta(hours=48),
            ))
        db.session.flush()

        # ── Risks ──
        risks_data = [
            (proj_main, '第三方依赖库安全漏洞', '发现Flask-Login存在CVE，需升级',
             'high', 'open', wang, xu, -5, 3),
            (proj_main, '数据导入性能瓶颈', '大批量CSV导入超过1000行时响应超时',
             'medium', 'open', sun, li, -3, 7),
            (proj_main, '前端兼容性问题', 'IE11不支持部分ES6语法',
             'low', 'resolved', zhang, None, -15, -5),
            (proj_main, '需求变更频繁', '客户连续3次修改需求范围，影响排期',
             'high', 'open', li, xu, -1, 10),
            (proj_ai, 'AI模型推理延迟过高', '本地Ollama推理单次>10秒，影响用户体验',
             'high', 'open', liu, li, -7, 5),
            (proj_ai, '训练数据隐私合规', '需确认训练数据不含用户隐私信息',
             'medium', 'open', liu, xu, -2, 14),
            (proj_mobile, '移动端触控交互冲突', '拖拽排序与页面滚动冲突',
             'medium', 'open', zhang, li, -4, 8),
            (proj_main, '数据库备份策略缺失', '当前无自动备份，存在数据丢失风险',
             'high', 'open', wang, xu, -10, -3),  # overdue
        ]
        risks = []
        for proj, title, desc, sev, status, owner_user, tracker, created_off, due_off in risks_data:
            r = Risk(
                project_id=proj.id, title=title, description=desc,
                severity=sev, status=status,
                owner=owner_user.name, owner_id=owner_user.id,
                tracker_id=tracker.id if tracker else None,
                due_date=today + timedelta(days=due_off),
                created_by=li.id,
                created_at=now + timedelta(days=created_off),
                owner_since=now + timedelta(days=created_off),
            )
            if status == 'resolved':
                r.resolved_at = now - timedelta(days=2)
                r.resolution = '已使用Babel转译解决'
            db.session.add(r)
            risks.append(r)
        db.session.flush()

        # Risk comments
        risk_comments = [
            (risks[0], wang, '已提交升级PR，等待测试验证'),
            (risks[0], huang, '升级后回归测试通过，但性能测试还未跑'),
            (risks[1], sun, '正在尝试分批导入方案'),
            (risks[3], li, '已和客户对齐，本周五前锁定需求范围'),
            (risks[4], liu, '尝试量化后推理时间降到3秒'),
            (risks[7], wang, '已设置crontab每日备份，待验证恢复流程'),
        ]
        for risk, user, content in risk_comments:
            db.session.add(RiskComment(
                risk_id=risk.id, user_id=user.id, content=content,
                created_at=now - timedelta(hours=12),
            ))
        db.session.flush()
        print(f'Created {len(risks_data)} risks with {len(risk_comments)} comments')

        # ── Todos ──
        todo_items_data = [
            # (user, title, status, category, due_date, done_date, req, sub_items)
            (wang, '修复登录IP绑定bug', 'done', 'work', today - timedelta(days=3), today - timedelta(days=3), r1,
             ['排查session冲突', '修改auto_login逻辑', '测试多用户场景']),
            (wang, '优化项目列表查询', 'done', 'work', today - timedelta(days=1), today - timedelta(days=1), r2,
             ['添加分页', '加索引']),
            (chen, '实现需求筛选器', 'todo', 'work', today + timedelta(days=2), None, r3,
             ['项目筛选', '状态筛选', '优先级筛选', '负责人筛选']),
            (chen, '需求编辑表单验证', 'todo', 'work', today + timedelta(days=5), None, r3_2, []),
            (zhang, '番茄钟UI优化', 'todo', 'work', today + timedelta(days=3), None, r4_2,
             ['倒计时动画', '完成音效']),
            (huang, '风险模块回归测试', 'todo', 'work', today + timedelta(days=1), None, r5,
             ['创建风险', '编辑风险', '删除权限', '评论功能']),
            (sun, '完成数据导出功能', 'todo', 'work', today, None, r10, ['CSV导出', 'Excel导出']),
            (liu, '调优Ollama模型参数', 'todo', 'work', today + timedelta(days=4), None, r_ai1, []),
            (li, '准备周五项目评审材料', 'todo', 'team', today + timedelta(days=3), None, None, []),
            (li, '整理本周风险跟踪表', 'done', 'risk', today, today, None, []),
            (zhang, '响应式断点调试', 'todo', 'work', today + timedelta(days=5), None, r_m1, []),
            (guo, '学习Tailwind CSS', 'todo', 'personal', today + timedelta(days=7), None, None, []),
            (xu, '编写测试规范文档', 'todo', 'team', today + timedelta(days=10), None, None, []),
            (wang, '代码review陈晓的PR', 'todo', 'work', today + timedelta(days=1), None, None, []),
            (yang, '设计激励页面原型', 'todo', 'work', today + timedelta(days=7), None, r9, []),
            # Some done today
            (huang, '编写风险测试用例', 'done', 'work', today, today, r5, []),
            (wang, '修复周报导出格式', 'done', 'work', today, today, r6, []),
        ]
        todos = []
        for user, title, status, cat, due, done, req, subs in todo_items_data:
            t = Todo(
                user_id=user.id, title=title, status=status, category=cat,
                due_date=due, done_date=done,
                created_date=due - timedelta(days=2) if due else today,
                created_at=now - timedelta(days=3),
            )
            db.session.add(t)
            db.session.flush()
            if req:
                db.session.execute(
                    db.text('INSERT INTO todo_requirements (todo_id, requirement_id) VALUES (:tid, :rid)'),
                    {'tid': t.id, 'rid': req.id},
                )
            for i, sub_title in enumerate(subs):
                db.session.add(TodoItem(
                    todo_id=t.id, title=sub_title,
                    is_done=(status == 'done'), sort_order=i,
                ))
            todos.append(t)

        # Pomodoro sessions for some todos
        for t in todos[:5]:
            if t.status == 'done':
                db.session.add(PomodoroSession(
                    todo_id=t.id, started_at=now - timedelta(hours=6),
                    minutes=45, completed=True,
                ))
            db.session.add(PomodoroSession(
                todo_id=t.id, started_at=now - timedelta(hours=3),
                minutes=25, completed=False,
            ))
        db.session.flush()
        print(f'Created {len(todo_items_data)} todos')

        # ── Recurring Todos ──
        recurring_data = [
            (li, '检查风险跟踪状态', 'weekdays', '1,3,5', None),
            (wang, '代码仓库巡检', 'weekly', None, None),
            (xu, '质量周报', 'weekly', None, None),
            (huang, '自动化测试执行', 'weekdays', '1,2,3,4,5', None),
            (zhou, '团队周会准备', 'weekly', None, None),
        ]
        for user, title, cycle, weekdays, monthly_days in recurring_data:
            db.session.add(RecurringTodo(
                user_id=user.id, title=title, cycle=cycle,
                weekdays=weekdays, monthly_days=monthly_days,
            ))
        db.session.flush()
        print(f'Created {len(recurring_data)} recurring todos')

        # ── Meetings ──
        meetings_data = [
            (proj_main, '项目启动会', today - timedelta(days=55),
             '周明,李婷,王磊,陈晓,张伟,黄丽,徐芳', '',
             '1. 项目背景介绍\n2. 里程碑计划确认\n3. 各模块负责人分工\n4. 风险识别'),
            (proj_main, '需求评审会议', today - timedelta(days=35),
             '李婷,王磊,陈晓,杨帆', '周明,徐芳',
             '1. 需求清单评审\n2. 优先级排序\n3. 工作量估算\n4. 待确认: 数据导入格式'),
            (proj_main, '周例会', today - timedelta(days=7),
             '李婷,王磊,陈晓,张伟,黄丽', '',
             '1. 本周进展同步\n2. 风险问题讨论\n3. 下周计划\n待办: 王磊修复导入性能'),
            (proj_ai, 'AI选型评审', today - timedelta(days=25),
             '刘洋,王磊,李婷', '周明',
             '1. Ollama vs OpenAI对比\n2. 本地部署方案\n3. 结论: 先用Ollama，后续按需切换'),
            (proj_main, '本周站会', today - timedelta(days=1),
             '李婷,王磊,陈晓,张伟,黄丽,孙鹏', '',
             '1. 陈晓: 需求编辑基本完成\n2. 张伟: 番茄钟开发中\n3. 孙鹏: 导出功能延期\n阻塞: 导入性能问题'),
        ]
        for proj, title, d, attendees, cc, content in meetings_data:
            db.session.add(Meeting(
                project_id=proj.id, title=title, date=d,
                attendees=attendees, cc=cc, content=content,
                created_by=li.id,
                created_at=datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc),
            ))
        db.session.flush()
        print(f'Created {len(meetings_data)} meetings')

        # ── Knowledge ──
        knowledge_data = [
            (proj_main, 'API接口文档', 'api', 'https://wiki.internal/api-docs', True),
            (proj_main, '编码规范', 'doc', 'https://wiki.internal/coding-standards', True),
            (proj_main, 'Git工作流指南', 'doc', 'https://wiki.internal/git-workflow', False),
            (proj_main, '部署手册', 'doc', 'https://wiki.internal/deploy-guide', True),
            (proj_ai, 'Ollama部署指南', 'doc', 'https://wiki.internal/ollama-setup', True),
            (proj_ai, 'Prompt工程最佳实践', 'wiki', 'https://wiki.internal/prompt-engineering', False),
            (proj_mobile, '响应式设计规范', 'design', 'https://figma.com/mobile-design', True),
        ]
        for proj, title, link_type, link, pinned in knowledge_data:
            db.session.add(Knowledge(
                project_id=proj.id, title=title, link_type=link_type,
                link=link, is_pinned=pinned, created_by=li.id,
            ))
        db.session.flush()
        print(f'Created {len(knowledge_data)} knowledge items')

        # ── AARs ──
        aar_data = [
            (proj_main, '需求评审复盘', 'milestone', 'TR1 需求评审', today - timedelta(days=30),
             '李婷,王磊,陈晓,杨帆',
             '按时完成需求评审', '评审发现15处需求描述不清晰',
             '需求模板不够规范，缺少验收标准字段', '增加需求模板，强制填写验收标准'),
            (proj_ai, 'AI选型复盘', 'custom', 'AI技术选型', today - timedelta(days=20),
             '刘洋,王磊',
             '选出最适合的AI方案', '本地Ollama性能达标但精度略低',
             'Ollama在特定场景下效果不稳定', '准备OpenAI fallback方案，建立效果评估基线'),
        ]
        for proj, title, trigger, trigger_ref, d, participants, goal, result, analysis, action in aar_data:
            db.session.add(AAR(
                project_id=proj.id, title=title, trigger=trigger,
                trigger_ref=trigger_ref, date=d, participants=participants,
                goal=goal, result=result, analysis=analysis, action=action,
                status='done', created_by=li.id,
            ))
        db.session.flush()
        print(f'Created {len(aar_data)} AARs')

        # ── Permission Items & Applications ──
        perm_items = [
            (proj_main, '代码仓库', 'GitLab', 'group/reqsys-platform', '平台代码仓库读写权限'),
            (proj_main, '生产服务器', 'SSH', 'prod-server-01', '生产环境SSH访问'),
            (proj_main, '数据库', 'MySQL', 'reqsys-db-prod', '生产数据库只读'),
            (proj_ai, 'GPU服务器', 'SSH', 'gpu-server-01', 'AI训练/推理服务器'),
        ]
        perm_objs = []
        for proj, cat, resource, repo, desc in perm_items:
            p = PermissionItem(
                project_id=proj.id, category=cat, resource=resource,
                repo_path=repo, description=desc, created_by=li.id,
            )
            db.session.add(p)
            perm_objs.append(p)
        db.session.flush()

        # Applications
        app_data = [
            (perm_objs[0], f'{chen.name}({to_pinyin(chen.name).split(" ")[0]}) {chen.employee_id}',
             chen.employee_id, '开发需要', 'approved', li, now - timedelta(days=10)),
            (perm_objs[0], f'{sun.name}({to_pinyin(sun.name).split(" ")[0]}) {sun.employee_id}',
             sun.employee_id, '开发需要', 'pending', None, None),
            (perm_objs[2], f'{wang.name}({to_pinyin(wang.name).split(" ")[0]}) {wang.employee_id}',
             wang.employee_id, '排查线上问题', 'approved', zhou, now - timedelta(days=5)),
            (perm_objs[3], f'{liu.name}({to_pinyin(liu.name).split(" ")[0]}) {liu.employee_id}',
             liu.employee_id, 'AI模型训练', 'approved', li, now - timedelta(days=20)),
        ]
        for item, applicant_name, eid, reason, status, approver, approved_at in app_data:
            db.session.add(PermissionApplication(
                item_id=item.id, applicant_name=applicant_name,
                applicant_eid=eid, reason=reason, status=status,
                submitted_by=li.id,
                approved_by=approver.id if approver else None,
                approved_at=approved_at,
            ))
        db.session.flush()
        print(f'Created {len(perm_items)} permission items with {len(app_data)} applications')

        # ── Incentives ──
        fund = IncentiveFund(
            name='Q1及时激励基金', source='instant', total_amount=10000,
            expires_at=today + timedelta(days=60),
            note='2026年Q1及时激励预算', created_by=admin.id,
        )
        db.session.add(fund)
        db.session.flush()

        incentive_data = [
            ('修复登录安全漏洞', 'professional', '及时发现并修复IP绑定安全问题', 'instant',
             wang, 'approved', 500, [wang]),
            ('AI需求解析创新方案', 'proactive', '主动研究并实现本地大模型集成方案', 'instant',
             liu, 'approved', 800, [liu, wang]),
            ('跨部门协作支援', 'beyond', '主动协助移动端团队解决前端难题', 'instant',
             zhang, 'submitted', None, [zhang]),
            ('代码质量改进', 'clean', '重构核心模块，代码覆盖率提升20%', 'improvement',
             chen, 'pending', 300, [chen]),
        ]
        for title, cat, desc, source, submitter, status, amount, nominees in incentive_data:
            inc = Incentive(
                title=title, category=cat, description=desc, source=source,
                submitted_by=submitter.id, status=status,
                amount=amount, fund_id=fund.id if amount else None,
                reviewed_by=li.id if status in ('approved', 'rejected') else None,
                reviewed_at=now - timedelta(days=3) if status == 'approved' else None,
                review_comment='表现优秀' if status == 'approved' else None,
                is_public=True, likes=len(nominees) * 3,
            )
            db.session.add(inc)
            db.session.flush()
            for u in nominees:
                db.session.execute(
                    db.text('INSERT INTO incentive_nominees (incentive_id, user_id) VALUES (:iid, :uid)'),
                    {'iid': inc.id, 'uid': u.id},
                )
        db.session.flush()
        print(f'Created {len(incentive_data)} incentives')

        # ── Standup Records ──
        standup_users = [wang, chen, zhang, liu, sun, huang]
        for u in standup_users:
            for day_offset in range(3):
                d = today - timedelta(days=day_offset)
                if d.weekday() >= 5:
                    continue
                db.session.add(StandupRecord(
                    user_id=u.id, date=d,
                    yesterday_done=f'完成{u.domain}相关任务',
                    today_plan=f'继续{u.domain}开发工作',
                    blocker='导入性能问题待解决' if u == sun and day_offset == 0 else None,
                    has_blocker=(u == sun and day_offset == 0),
                ))
        db.session.flush()
        print(f'Created standup records')

        # ── Follow projects ──
        for u in [wang, chen, zhang, liu, huang]:
            u.followed_projects.append(proj_main)
        for u in [liu, wang]:
            u.followed_projects.append(proj_ai)
        for u in [zhang, guo]:
            u.followed_projects.append(proj_mobile)

        db.session.commit()
        print('\n✓ All test data created successfully!')
        print(f'  Users: {User.query.count()}')
        print(f'  Projects: {Project.query.count()}')
        print(f'  Requirements: {Requirement.query.count()}')
        print(f'  Risks: {Risk.query.count()}')
        print(f'  Todos: {Todo.query.count()}')
        print(f'  Meetings: {Meeting.query.count()}')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Initialize database and optionally seed test data')
    parser.add_argument('--test-data', action='store_true', help='Create rich test data for development')
    parser.add_argument('--reset', action='store_true', help='Delete existing DB and recreate from scratch')
    args = parser.parse_args()

    if args.reset:
        import shutil
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance', 'reqsys.db')
        if os.path.exists(db_path):
            backup = db_path + '.bak'
            shutil.copy2(db_path, backup)
            os.remove(db_path)
            print(f'DB deleted (backup: {backup})')

    seed()

    if args.test_data:
        seed_test_data()
