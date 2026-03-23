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
