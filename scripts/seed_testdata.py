"""一键导入测试数据，用于手动测试。可重复执行（幂等）。
用法: python scripts/seed_testdata.py [--clean]
  --clean  先清除旧测试数据再导入
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.incentive import Incentive
from app.models.meeting import Meeting
from app.models.project import Milestone, Project
from app.models.project_member import ProjectMember
from app.models.requirement import Requirement
from app.models.risk import Risk
from app.models.todo import Todo, TodoItem
from app.models.user import Group, Role, User
from app.utils.pinyin import to_pinyin

# ── 测试数据定义 ──────────────────────────────────────────

TEST_GROUPS = ['前端组', '后端组', '测试组']

TEST_USERS = [
    {'eid': 't00000001', 'name': '张三', 'group': '后端组', 'roles': ['DE'], 'ip': '10.0.0.101', 'manager': '赵六 t00000004', 'domain': '技术开发'},
    {'eid': 't00000002', 'name': '李四', 'group': '前端组', 'roles': ['DE'], 'ip': '10.0.0.102', 'manager': '赵六 t00000004', 'domain': '业务开发'},
    {'eid': 't00000003', 'name': '王五', 'group': '测试组', 'roles': ['DE'], 'ip': '10.0.0.103', 'manager': '赵六 t00000004', 'domain': '产品测试'},
    {'eid': 't00000004', 'name': '赵六', 'group': '后端组', 'roles': ['DE', 'PL'], 'ip': '10.0.0.104', 'manager': '陈总 c00990001', 'domain': '芯片验证'},
    {'eid': 't00000005', 'name': '孙七', 'group': '前端组', 'roles': ['DE'], 'ip': '10.0.0.105', 'manager': '赵六 t00000004', 'domain': '功能仿真'},
    # 扩充用户
    {'eid': 't00000006', 'name': '周杰', 'group': '后端组', 'roles': ['DE'], 'ip': '10.0.0.106', 'manager': '赵六 t00000004', 'domain': '后端开发'},
    {'eid': 't00000007', 'name': '吴磊', 'group': '后端组', 'roles': ['DE'], 'ip': '10.0.0.107', 'manager': '赵六 t00000004', 'domain': '后端开发'},
    {'eid': 't00000008', 'name': '郑涛', 'group': '前端组', 'roles': ['DE'], 'ip': '10.0.0.108', 'manager': '赵六 t00000004', 'domain': '前端开发'},
    {'eid': 't00000009', 'name': '冯刚', 'group': '前端组', 'roles': ['DE'], 'ip': '10.0.0.109', 'manager': '赵六 t00000004', 'domain': '前端开发'},
    {'eid': 't00000010', 'name': '陈静', 'group': '测试组', 'roles': ['DE'], 'ip': '10.0.0.110', 'manager': '赵六 t00000004', 'domain': '测试'},
    {'eid': 't00000011', 'name': '褚亮', 'group': '测试组', 'roles': ['DE'], 'ip': '10.0.0.111', 'manager': '赵六 t00000004', 'domain': '测试'},
    {'eid': 't00000012', 'name': '卫敏', 'group': '后端组', 'roles': ['DE'], 'ip': '10.0.0.112', 'manager': '赵六 t00000004', 'domain': '架构设计'},
    {'eid': 't00000013', 'name': '蒋华', 'group': '后端组', 'roles': ['DE'], 'ip': '10.0.0.113', 'manager': '赵六 t00000004', 'domain': '后端开发'},
    {'eid': 't00000014', 'name': '沈洁', 'group': '前端组', 'roles': ['DE'], 'ip': '10.0.0.114', 'manager': '赵六 t00000004', 'domain': '前端开发'},
    {'eid': 't00000015', 'name': '韩鹏', 'group': '测试组', 'roles': ['DE'], 'ip': '10.0.0.115', 'manager': '赵六 t00000004', 'domain': '测试'},
    {'eid': 't00000016', 'name': '杨帆', 'group': '后端组', 'roles': ['DE'], 'ip': '10.0.0.116', 'manager': '赵六 t00000004', 'domain': '后端开发'},
    {'eid': 't00000017', 'name': '朱颖', 'group': '前端组', 'roles': ['DE'], 'ip': '10.0.0.117', 'manager': '赵六 t00000004', 'domain': '前端开发'},
    {'eid': 't00000018', 'name': '秦峰', 'group': '后端组', 'roles': ['DE'], 'ip': '10.0.0.118', 'manager': '赵六 t00000004', 'domain': '后端开发'},
    {'eid': 't00000019', 'name': '尤丽', 'group': '测试组', 'roles': ['DE'], 'ip': '10.0.0.119', 'manager': '赵六 t00000004', 'domain': '质量管理'},
    {'eid': 't00000020', 'name': '许强', 'group': '后端组', 'roles': ['DE', 'PL'], 'ip': '10.0.0.120', 'manager': '陈总 c00990001', 'domain': '技术管理'},
]

TEST_PROJECTS = [
    {'name': '商城后台系统', 'desc': '电商后台管理系统重构', 'children': [
        {'name': '用户中心模块', 'desc': '用户注册登录、权限管理、个人信息'},
        {'name': '订单系统模块', 'desc': '订单创建、支付、退款、物流'},
        {'name': '商品管理模块', 'desc': '商品CRUD、搜索、分类'},
    ]},
    {'name': '移动端APP', 'desc': 'iOS/Android客户端开发'},
]

TEST_REQUIREMENTS = [
    # (project_idx, title, status, priority, assignee_eid, estimate_days, source)
    (0, '用户管理模块重构', 'in_dev', 'high', 't00000001', 5, 'coding'),
    (0, '订单列表性能优化', 'pending_dev', 'medium', 't00000004', 3, 'coding'),
    (0, '权限系统设计', 'pending_review', 'high', None, 8, 'analysis'),
    (0, '商品搜索功能', 'in_test', 'medium', 't00000002', 4, 'coding'),
    (0, '支付接口对接', 'in_dev', 'high', 't00000001', 6, 'coding'),
    (0, '数据导出功能', 'done', 'low', 't00000003', 2, 'coding'),
    (1, '首页UI改版', 'in_dev', 'high', 't00000002', 7, 'coding'),
    (1, '推送通知集成', 'pending_dev', 'medium', 't00000005', 4, 'coding'),
    (1, '离线缓存方案', 'pending_review', 'low', None, 3, 'analysis'),
    (1, '用户登录流程优化', 'done', 'medium', 't00000005', 2, 'coding'),
]

TEST_MEETINGS = [
    # (project_idx, title, days_ago, attendees)
    (0, '商城后台需求评审', 3, '张三,李四,赵六'),
    (0, '订单模块技术方案讨论', 1, '张三,赵六'),
    (1, 'APP首页改版设计评审', 5, '李四,孙七,王五'),
    (1, '推送功能需求对齐', 2, '孙七,赵六'),
]

TEST_RISKS = [
    # (project_idx, title, severity, owner, meeting_idx, days_until_due)
    (0, '订单高并发可能导致超卖', 'high', '张三', 1, 5),
    (0, '第三方支付SDK证书即将过期', 'medium', '赵六', None, 10),
    (1, 'iOS审核政策变更影响推送', 'high', '孙七', 3, 7),
    (1, 'APP包体积超过200MB', 'low', '李四', 2, 14),
]

TEST_TODOS = [
    # (user_eid, title, category, status, req_idx_or_none)
    ('t00000001', '完成用户管理模块数据库设计', 'work', 'todo', 0),
    ('t00000001', '修复登录token过期问题', 'work', 'todo', None),
    ('t00000001', '代码review李四的PR', 'team', 'todo', None),
    ('t00000002', '首页轮播组件开发', 'work', 'todo', 6),
    ('t00000002', '修复样式兼容性bug', 'work', 'done', 3),
    ('t00000003', '编写订单模块测试用例', 'work', 'todo', 1),
    ('t00000003', '搭建自动化测试环境', 'team', 'todo', None),
    ('t00000004', '需求排期会议准备', 'team', 'todo', None),
    ('t00000004', '审核支付模块安全方案', 'work', 'todo', 4),
    ('t00000005', '推送SDK集成调研', 'work', 'todo', 7),
    ('t00000005', '整理技术债清单', 'personal', 'todo', None),
]

TEST_PROJECT_MEMBERS = [
    # 商城后台系统(idx=0): 5种角色, 3:1:1:1:2 比例, 共20人
    # DEV(后端开发) - 8人 (3份)
    (0, 't00000001', 'DEV(订单模块)', True),
    (0, 't00000006', 'DEV(支付网关)', True),
    (0, 't00000007', 'DEV(用户中心)', True),
    (0, 't00000013', 'DEV(商品搜索)', True),
    (0, 't00000016', 'DEV(库存系统)', True),
    (0, 't00000018', 'DEV(数据同步)', True),
    (0, 't00000012', 'DEV(缓存架构)', True),
    (0, 't00000004', 'DEV(API网关)', True),
    # DEV(前端开发) - 5人 (2份)
    (0, 't00000002', 'DEV(商品页面)', True),
    (0, 't00000008', 'DEV(订单流程)', True),
    (0, 't00000009', 'DEV(营销活动)', True),
    (0, 't00000014', 'DEV(管理后台)', True),
    (0, 't00000017', 'DEV(数据看板)', True),
    # PL(技术负责人) - 2人 (1份)
    (0, 't00000004', 'PL', True),
    (0, 't00000020', 'PL', True),
    # TE(测试) - 2人 (1份)
    (0, 't00000003', 'TE(接口自动化)', True),
    (0, 't00000010', 'TE(性能压测)', True),
    # QA(质量管理) - 3人 (1份)
    (0, 't00000011', 'QA(发布验收)', True),
    (0, 't00000015', 'QA(回归测试)', True),
    (0, 't00000019', 'QA(流程审计)', True),
    # 移动端APP(idx=1)
    (1, 't00000004', 'PM', True),
    (1, 't00000002', 'DEV(iOS)', True),
    (1, 't00000005', 'DEV(Android)', True),
    (1, 't00000003', 'TE(模型A)', False),
    (1, 't00000005', 'DEV(推送模块)', True),
]

TEST_INCENTIVES = [
    # (submitter_eid, nominee_eid, title, desc, category, status)
    ('t00000004', 't00000001', '紧急修复线上bug', '凌晨2点紧急修复订单系统异常，保障了次日促销活动', 'beyond', 'submitted'),
    ('t00000004', 't00000002', '前端性能优化', '首页加载时间从3s优化到800ms，用户体验显著提升', 'professional', 'submitted'),
    ('t00000001', 't00000003', '测试覆盖率提升', '核心模块测试覆盖率从40%提升到85%', 'professional', 'submitted'),
]

today = date.today()


def clean_test_data():
    """清除测试数据（通过工号前缀 t000 识别）。"""
    test_users = User.query.filter(User.employee_id.like('t00%')).all()
    test_uids = {u.id for u in test_users}
    if not test_uids:
        print('无测试数据需清除')
        return

    # 按依赖顺序删除
    TodoItem.query.filter(TodoItem.todo_id.in_(
        db.session.query(Todo.id).filter(Todo.user_id.in_(test_uids))
    )).delete(synchronize_session=False)
    Todo.query.filter(Todo.user_id.in_(test_uids)).delete(synchronize_session=False)
    Incentive.query.filter(Incentive.submitted_by.in_(test_uids)).delete(synchronize_session=False)

    # 删除测试项目关联的数据
    test_projects = Project.query.filter(Project.created_by.in_(test_uids)).all()
    test_pids = {p.id for p in test_projects}
    if test_pids:
        ProjectMember.query.filter(ProjectMember.project_id.in_(test_pids)).delete(synchronize_session=False)
        Risk.query.filter(Risk.project_id.in_(test_pids)).delete(synchronize_session=False)
        Meeting.query.filter(Meeting.project_id.in_(test_pids)).delete(synchronize_session=False)
        Requirement.query.filter(Requirement.project_id.in_(test_pids)).delete(synchronize_session=False)
        Milestone.query.filter(Milestone.project_id.in_(test_pids)).delete(synchronize_session=False)
        Project.query.filter(Project.id.in_(test_pids)).delete(synchronize_session=False)

    for u in test_users:
        u.roles = []
    db.session.flush()
    User.query.filter(User.id.in_(test_uids)).delete(synchronize_session=False)

    db.session.commit()
    print(f'已清除测试数据: {len(test_users)} 用户, {len(test_pids)} 项目')


def seed():
    app = create_app()
    with app.app_context():
        if '--clean' in sys.argv:
            clean_test_data()

        # ── Groups ──
        for g in TEST_GROUPS:
            if not Group.query.filter_by(name=g).first():
                db.session.add(Group(name=g))
        db.session.commit()

        # ── Users ──
        users = {}  # eid → User
        for u in TEST_USERS:
            existing = User.query.filter_by(employee_id=u['eid']).first()
            if existing:
                users[u['eid']] = existing
                continue
            roles = Role.query.filter(Role.name.in_(u['roles'])).all()
            user = User(
                employee_id=u['eid'], name=u['name'],
                pinyin=to_pinyin(u['name']),
                ip_address=u['ip'], group=u['group'],
                manager=u.get('manager'), domain=u.get('domain'),
                roles=roles,
            )
            db.session.add(user)
            db.session.flush()
            users[u['eid']] = user
        db.session.commit()
        print(f'用户: {len(users)}')

        # 找一个管理员作为项目创建者
        creator = users.get('t00000004') or User.query.first()

        # ── Projects ──
        # Build a lookup: project_idx → PM eid from TEST_PROJECT_MEMBERS
        _pm_by_pidx = {}
        for pidx, eid, role, *_ in TEST_PROJECT_MEMBERS:
            if role == 'PM' and pidx not in _pm_by_pidx:
                _pm_by_pidx[pidx] = eid

        projects = []
        for pi, p in enumerate(TEST_PROJECTS):
            existing = Project.query.filter_by(name=p['name']).first()
            if existing:
                projects.append(existing)
                continue
            # owner = PM member if defined, otherwise None
            pm_user = users.get(_pm_by_pidx.get(pi)) if _pm_by_pidx.get(pi) else None
            proj = Project(name=p['name'], description=p['desc'],
                           created_by=creator.id,
                           owner_id=pm_user.id if pm_user else None)
            db.session.add(proj)
            db.session.flush()
            # Child projects (copy parent milestones if none)
            for child in p.get('children', []):
                existing_child = Project.query.filter_by(name=child['name'], parent_id=proj.id).first()
                if not existing_child:
                    cp = Project(name=child['name'], description=child['desc'],
                                 parent_id=proj.id, created_by=creator.id,
                                 status='active')
                    db.session.add(cp)
                    db.session.flush()
                    # Copy parent milestones
                    for ms in proj.milestones:
                        db.session.add(Milestone(project_id=cp.id, name=ms.name,
                                                 due_date=ms.due_date, status=ms.status))
            projects.append(proj)
        db.session.commit()
        print(f'项目: {len(projects)}')

        # ── Requirements ──
        req_objects = []
        for i, (pidx, title, status, prio, a_eid, est, src) in enumerate(TEST_REQUIREMENTS):
            num = f'REQ-T{i+1:03d}'
            existing = Requirement.query.filter_by(number=num).first()
            if existing:
                req_objects.append(existing)
                continue
            assignee = users.get(a_eid) if a_eid else None
            req = Requirement(
                number=num, project_id=projects[pidx].id,
                title=title, status=status, priority=prio,
                assignee_id=assignee.id if assignee else None,
                estimate_days=est, source=src,
                start_date=today - timedelta(days=est+3),
                due_date=today + timedelta(days=est),
                created_by=creator.id,
            )
            db.session.add(req)
            db.session.flush()
            req_objects.append(req)
        db.session.commit()
        print(f'需求: {len(req_objects)}')

        # ── Meetings ──
        meeting_objects = []
        for pidx, title, days_ago, attendees in TEST_MEETINGS:
            existing = Meeting.query.filter_by(title=title, project_id=projects[pidx].id).first()
            if existing:
                meeting_objects.append(existing)
                continue
            m = Meeting(
                project_id=projects[pidx].id, title=title,
                date=today - timedelta(days=days_ago),
                attendees=attendees,
                content=f'{title}的会议纪要内容。\n讨论了相关技术方案和排期。',
                created_by=creator.id,
            )
            db.session.add(m)
            db.session.flush()
            meeting_objects.append(m)
        db.session.commit()
        print(f'会议: {len(meeting_objects)}')

        # ── Risks ──
        risk_count = 0
        for pidx, title, sev, owner, midx, due_days in TEST_RISKS:
            existing = Risk.query.filter_by(title=title, project_id=projects[pidx].id).first()
            if existing:
                risk_count += 1
                continue
            owner_user = users.get(next((u['eid'] for u in TEST_USERS if u['name'] == owner), ''))
            r = Risk(
                project_id=projects[pidx].id, title=title,
                severity=sev, owner=owner,
                owner_id=owner_user.id if owner_user else None,
                meeting_id=meeting_objects[midx].id if midx is not None else None,
                due_date=today + timedelta(days=due_days),
                created_by=creator.id,
            )
            db.session.add(r)
            risk_count += 1
        db.session.commit()
        print(f'风险: {risk_count}')

        # ── Project Members ──
        member_count = 0
        for pidx, u_eid, prole, is_key in TEST_PROJECT_MEMBERS:
            user = users[u_eid]
            proj = projects[pidx]
            existing = ProjectMember.query.filter_by(
                project_id=proj.id, user_id=user.id, project_role=prole
            ).first()
            if existing:
                member_count += 1
                continue
            pm = ProjectMember(
                project_id=proj.id, user_id=user.id,
                project_role=prole, is_key=is_key,
            )
            db.session.add(pm)
            member_count += 1
        db.session.commit()
        print(f'项目成员: {member_count}')

        # ── Todos ──
        todo_count = 0
        db.session.expire_all()  # clear dirty state from loaded req_objects
        for u_eid, title, cat, status, req_idx in TEST_TODOS:
            user = users[u_eid]
            existing = Todo.query.filter_by(user_id=user.id, title=title).first()
            if existing:
                todo_count += 1
                continue
            t = Todo(
                user_id=user.id, title=title, category=cat,
                status=status, due_date=today,
                done_date=today if status == 'done' else None,
            )
            db.session.add(t)
            db.session.flush()
            if req_idx is not None and req_idx < len(req_objects):
                db.session.execute(
                    db.text('INSERT OR IGNORE INTO todo_requirements (todo_id, requirement_id) VALUES (:tid, :rid)'),
                    {'tid': t.id, 'rid': req_objects[req_idx].id}
                )
            t.items.append(TodoItem(title=title, sort_order=0,
                                    is_done=(status == 'done')))
            todo_count += 1
        db.session.commit()
        print(f'Todo: {todo_count}')

        # ── Incentives ──
        inc_count = 0
        db.session.expire_all()
        for sub_eid, nom_eid, title, desc, cat, st in TEST_INCENTIVES:
            submitter = users[sub_eid]
            nominee = users[nom_eid]
            existing = Incentive.query.filter_by(title=title, submitted_by=submitter.id).first()
            if existing:
                inc_count += 1
                continue
            inc = Incentive(
                title=title, description=desc, category=cat,
                status=st, submitted_by=submitter.id,
            )
            db.session.add(inc)
            db.session.flush()
            db.session.execute(
                db.text('INSERT OR IGNORE INTO incentive_nominees (incentive_id, user_id) VALUES (:iid, :uid)'),
                {'iid': inc.id, 'uid': nominee.id}
            )
            inc_count += 1
        db.session.commit()
        print(f'激励: {inc_count}')

        print('\n✅ 测试数据导入完成！')
        print(f'  测试用户工号: {", ".join(u["eid"] for u in TEST_USERS)}')
        print(f'  测试需求编号: REQ-T001 ~ REQ-T{len(TEST_REQUIREMENTS):03d}')


if __name__ == '__main__':
    seed()
