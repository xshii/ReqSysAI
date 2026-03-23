"""
项目管理页测试用例 (project/)
用法: python -m pytest tests/test_project.py -v
"""
import os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope='module')
def app():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    with app.app_context():
        _db.create_all()
        from app.models.user import User, Role
        r = Role(name='Admin')
        _db.session.add(r)
        _db.session.flush()
        u = User(employee_id='a00000001', name='管理员', ip_address='127.0.0.1')
        u.roles.append(r)
        _db.session.add(u)
        _db.session.commit()
        yield app


@pytest.fixture(autouse=True)
def rollback(app):
    yield
    with app.app_context():
        _db.session.rollback()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = '1'
        yield c


def _make_project(name='测试项目'):
    from app.models.project import Project
    p = Project(name=name, created_by=1, status='active')
    _db.session.add(p)
    _db.session.flush()
    return p


# ─── 项目 CRUD ──────────────────────────────────────────────

class TestProjectCRUD:
    """项目创建、列表、详情"""

    def test_project_list(self, client, app):
        with app.app_context():
            _make_project('列表项目')
            _db.session.commit()
        resp = client.get('/projects/')
        assert resp.status_code == 200
        assert '列表项目' in resp.data.decode()

    def test_create_project(self, client, app):
        resp = client.post('/projects/new', data={
            'name': '新建项目',
            'description': '测试描述',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Project
            assert Project.query.filter_by(name='新建项目').first() is not None

    def test_project_detail(self, client, app):
        with app.app_context():
            p = _make_project('详情项目')
            _db.session.commit()
            pid = p.id
        resp = client.get(f'/projects/{pid}')
        assert resp.status_code == 200
        assert '详情项目' in resp.data.decode()

    def test_toggle_follow(self, client, app):
        with app.app_context():
            p = _make_project('关注项目')
            _db.session.commit()
            pid = p.id
        resp = client.post(f'/projects/{pid}/follow',
                           headers={'Content-Type': 'application/json'})
        data = resp.get_json()
        assert data is not None
        assert data['ok'] is True


# ─── 里程碑 ─────────────────────────────────────────────────

class TestMilestone:
    """里程碑管理"""

    def test_create_milestone(self, client, app):
        with app.app_context():
            p = _make_project('里程碑项目')
            _db.session.commit()
            pid = p.id
        resp = client.post(f'/projects/{pid}/milestones/new', data={
            'title': '版本1.0',
        }, follow_redirects=True)
        assert resp.status_code == 200


# ─── 风险 ───────────────────────────────────────────────────

class TestRisk:
    """项目风险管理"""

    def test_add_risk(self, client, app):
        with app.app_context():
            p = _make_project('风险项目')
            _db.session.commit()
            pid = p.id
        resp = client.post(f'/projects/{pid}/risks/add', data={
            'title': '性能风险',
            'severity': 'high',
            'due_date': '2026-04-15',
        }, follow_redirects=True)
        assert resp.status_code == 200


# ─── 项目编辑（Tab 布局）────────────────────────────────────

class TestProjectEdit:
    """项目编辑页 — 基本信息 / 里程碑 / 成员 三个 Tab"""

    def test_edit_page_loads(self, client, app):
        """编辑页正常加载，包含三个 tab"""
        with app.app_context():
            p = _make_project('编辑测试')
            _db.session.commit()
            pid = p.id
        resp = client.get(f'/projects/{pid}/edit')
        html = resp.data.decode()
        assert resp.status_code == 200
        assert 'tabBasic' in html
        assert 'tabMilestone' in html
        assert 'tabMembers' in html

    def test_save_basic_info(self, client, app):
        """基本信息 tab 保存"""
        with app.app_context():
            p = _make_project('改名前')
            _db.session.commit()
            pid = p.id
        resp = client.post(f'/projects/{pid}/edit', data={
            'name': '改名后', 'parent_id': '0', 'description': '新目标',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Project
            p = _db.session.get(Project, pid)
            assert p.name == '改名后'
            assert p.description == '新目标'

    def test_save_milestones(self, client, app):
        """里程碑 tab 保存 — 日期字符串正确转为 date 对象"""
        with app.app_context():
            p = _make_project('里程碑保存')
            _db.session.commit()
            pid = p.id
        resp = client.post(f'/projects/{pid}/edit', data={
            'name': '里程碑保存', 'parent_id': '0', 'description': '',
            'ms_name': ['Charter', 'TR1', 'GA'],
            'ms_date': ['2026-04-01', '2026-05-15', '2026-06-30'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Milestone
            milestones = Milestone.query.filter_by(project_id=pid).order_by(Milestone.id).all()
            assert len(milestones) == 3
            assert milestones[0].name == 'Charter'
            assert milestones[0].due_date == date(2026, 4, 1)
            assert milestones[2].name == 'GA'
            assert milestones[2].due_date == date(2026, 6, 30)

    def test_save_milestones_empty_date(self, client, app):
        """里程碑日期为空不报错"""
        with app.app_context():
            p = _make_project('空日期')
            _db.session.commit()
            pid = p.id
        resp = client.post(f'/projects/{pid}/edit', data={
            'name': '空日期', 'parent_id': '0', 'description': '',
            'ms_name': ['无日期里程碑'],
            'ms_date': [''],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Milestone
            ms = Milestone.query.filter_by(project_id=pid).first()
            assert ms is not None
            assert ms.due_date is None

    def test_save_milestones_replaces_old(self, client, app):
        """保存里程碑时覆盖旧数据"""
        with app.app_context():
            from app.models.project import Milestone
            p = _make_project('覆盖旧')
            _db.session.flush()
            _db.session.add(Milestone(project_id=p.id, name='旧的', status='active'))
            _db.session.commit()
            pid = p.id
        # 保存新的里程碑
        resp = client.post(f'/projects/{pid}/edit', data={
            'name': '覆盖旧', 'parent_id': '0', 'description': '',
            'ms_name': ['新A', '新B'],
            'ms_date': ['2026-07-01', '2026-08-01'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Milestone
            milestones = Milestone.query.filter_by(project_id=pid).all()
            assert len(milestones) == 2
            names = {m.name for m in milestones}
            assert '旧的' not in names
            assert '新A' in names

    def test_edit_shows_existing_milestones(self, client, app):
        """编辑页预填已有里程碑"""
        with app.app_context():
            from app.models.project import Milestone
            p = _make_project('已有里程碑')
            _db.session.flush()
            _db.session.add(Milestone(project_id=p.id, name='PDCP',
                                      due_date=date(2026, 5, 1), status='active'))
            _db.session.commit()
            pid = p.id
        resp = client.get(f'/projects/{pid}/edit')
        html = resp.data.decode()
        assert 'PDCP' in html
        assert '2026-05-01' in html

    def test_edit_shows_members_tab(self, client, app):
        """编辑页包含成员 tab"""
        with app.app_context():
            p = _make_project('成员tab')
            _db.session.commit()
            pid = p.id
        resp = client.get(f'/projects/{pid}/edit')
        html = resp.data.decode()
        assert 'tabMembers' in html
        assert '成员' in html

    def test_status_toggle(self, client, app):
        """项目状态切换"""
        with app.app_context():
            p = _make_project('状态切换')
            _db.session.commit()
            pid = p.id
        # active → completed
        resp = client.post(f'/projects/{pid}/status', data={
            'status': 'completed',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Project
            assert _db.session.get(Project, pid).status == 'completed'
        # completed → active
        resp = client.post(f'/projects/{pid}/status', data={
            'status': 'active',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Project
            assert _db.session.get(Project, pid).status == 'active'

    def test_archived_status_rejected(self, client, app):
        """已归档状态被拒绝（已删除）"""
        with app.app_context():
            p = _make_project('归档拒绝')
            _db.session.commit()
            pid = p.id
        resp = client.post(f'/projects/{pid}/status', data={
            'status': 'archived',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import Project
            assert _db.session.get(Project, pid).status == 'active'  # unchanged


# ─── 里程碑模板 CRUD（项目级）──────────────────────────────

class TestMilestoneTemplateCRUD:
    """里程碑模板在项目编辑页内管理"""

    def test_create_template(self, client, app):
        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '项目内模板',
            'item_name': ['开始', '结束'],
            'item_offset': ['0', '+14天'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            assert MilestoneTemplate.query.filter_by(name='项目内模板').first() is not None

    def test_copy_template(self, client, app):
        """复制模板"""
        with app.app_context():
            from app.models.project import MilestoneTemplate, MilestoneTemplateItem
            t = MilestoneTemplate(name='原始模板')
            t.items.append(MilestoneTemplateItem(name='A', offset_days=0, sort_order=0))
            t.items.append(MilestoneTemplateItem(name='B', offset_days=7, sort_order=1))
            _db.session.add(t)
            _db.session.commit()
            tid = t.id

        resp = client.post('/projects/api/templates', json={
            'action': 'copy', 'id': tid,
        })
        data = resp.get_json()
        assert data['ok'] is True
        assert '副本' in data['name']

        with app.app_context():
            from app.models.project import MilestoneTemplate
            copy = MilestoneTemplate.query.filter_by(name='原始模板（副本）').first()
            assert copy is not None
            assert len(copy.items) == 2

    def test_delete_template(self, client, app):
        with app.app_context():
            from app.models.project import MilestoneTemplate
            t = MilestoneTemplate(name='要删模板')
            _db.session.add(t)
            _db.session.commit()
            tid = t.id
        resp = client.post('/projects/milestone-templates', data={
            'action': 'delete', 'template_id': str(tid),
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            assert _db.session.get(MilestoneTemplate, tid) is None

    def test_edit_template(self, client, app):
        with app.app_context():
            from app.models.project import MilestoneTemplate, MilestoneTemplateItem
            t = MilestoneTemplate(name='编辑模板')
            t.items.append(MilestoneTemplateItem(name='旧', offset_days=0, sort_order=0))
            _db.session.add(t)
            _db.session.commit()
            tid = t.id
        resp = client.post('/projects/milestone-templates', data={
            'action': 'edit', 'template_id': str(tid),
            'name': '改后', 'description': '',
            'item_name': ['新A', '新B'],
            'item_offset': ['0', '+7天'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            t = _db.session.get(MilestoneTemplate, tid)
            assert t.name == '改后'
            assert len(t.items) == 2
            assert t.items[1].offset_days == 7
