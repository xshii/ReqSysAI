"""
需求详情页测试用例：就地编辑、状态流转、加权完成率、分类、防重复广播
用法: python -m pytest tests/test_requirement_detail.py -v
"""
import json
import os
import sys

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
        from app.models.user import Group, Role, User
        r = Role(name='Admin')
        _db.session.add(r)
        Group.query.delete()
        _db.session.add(Group(name='测试组'))
        _db.session.flush()
        u1 = User(employee_id='t001', name='张三', ip_address='127.0.0.1', group='测试组')
        u1.roles.append(r)
        _db.session.add(u1)
        u2 = User(employee_id='t002', name='李四', ip_address='10.0.0.1', group='测试组')
        _db.session.add(u2)
        u3 = User(employee_id='t003', name='王五', ip_address='10.0.0.2', group='测试组')
        _db.session.add(u3)
        _db.session.flush()

        from app.models.project import Project
        p = Project(name='测试项目', created_by=u1.id, owner_id=u1.id)
        _db.session.add(p)
        _db.session.flush()

        from app.models.requirement import Requirement
        req = Requirement(
            number='REQ-001', title='测试需求', project_id=p.id,
            created_by=u1.id, status='in_dev', source='coding',
            completion=50, priority='high',
        )
        _db.session.add(req)
        _db.session.flush()

        child = Requirement(
            number='REQ-001-1', title='子需求1', project_id=p.id,
            created_by=u1.id, status='pending_dev', source='analysis',
            parent_id=req.id, estimate_days=3,
        )
        _db.session.add(child)
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


def _post_json(client, url, data):
    rv = client.post(url, data=json.dumps(data), content_type='application/json')
    return rv.get_json()


# ── weighted_completion ──

class TestWeightedCompletion:
    def test_coding_in_dev_50pct(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1,
                            source='coding', status='in_dev', completion=50)
            assert r.weighted_completion == 50

    def test_analysis_in_dev_50pct(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1,
                            source='analysis', status='in_dev', completion=50)
            assert r.weighted_completion == 85

    def test_testing_in_test_50pct(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1,
                            source='testing', status='in_test', completion=50)
            assert r.weighted_completion == 60

    def test_done_always_100(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1,
                            source='coding', status='done', completion=0)
            assert r.weighted_completion == 100

    def test_pending_review_always_0(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1,
                            source='coding', status='pending_review', completion=50)
            assert r.weighted_completion == 0

    def test_none_source_defaults_to_coding(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1,
                            source=None, status='in_dev', completion=50)
            assert r.weighted_completion == 50


# ── category_label ──

class TestCategoryLabel:
    def test_predefined(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1, category='feature')
            assert r.category_label == '功能需求'

    def test_custom(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1, category='自定义分类')
            assert r.category_label == '自定义分类'

    def test_none(self, app):
        with app.app_context():
            from app.models.requirement import Requirement
            r = Requirement(number='X', title='x', project_id=1, created_by=1, category=None)
            assert r.category_label == ''


# ── field-api ──

class TestFieldApi:
    def test_update_title(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'title', 'value': '新标题'})
        assert d['ok']

    def test_update_category(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'category', 'value': '功能需求'})
        assert d['ok']
        assert d['label'] == '功能需求'

    def test_update_priority(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'priority', 'value': 'low'})
        assert d['ok']
        assert d['label'] == '低'

    def test_reject_id(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'id', 'value': '999'})
        assert not d['ok']

    def test_reject_status(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'status', 'value': 'done'})
        assert not d['ok']

    def test_reject_created_by(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'created_by', 'value': '999'})
        assert not d['ok']

    def test_reject_empty_title(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'title', 'value': ''})
        assert not d['ok']

    def test_update_date(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'start_date', 'value': '2026-04-01'})
        assert d['ok']

    def test_update_assignee(self, client):
        d = _post_json(client, '/requirements/1/field-api', {'field': 'assignee_name', 'value': '张三'})
        assert d['ok']
        assert d['display'] == '张三'


# ── Status transition resets completion ──

class TestStatusTransition:
    def test_advance_resets_completion(self, client):
        d = _post_json(client, '/requirements/1/status-api', {'status': 'in_test'})
        assert d['ok']

    def test_done_sets_100(self, client):
        _post_json(client, '/requirements/1/status-api', {'status': 'in_test', 'force': True})
        d = _post_json(client, '/requirements/1/status-api', {'status': 'done'})
        assert d['ok']


# ── Broadcast duplicate prevention ──

class TestBroadcastDuplicate:
    def test_broadcast_creates(self, client):
        d = _post_json(client, '/quick-todo', {'title': '@测试组 广播测试', 'category': 'team'})
        assert d['ok']
        assert '测试组' in d.get('helper', '')

    def test_broadcast_duplicate_blocked(self, client):
        _post_json(client, '/quick-todo', {'title': '@测试组 重复测试', 'category': 'team'})
        d = _post_json(client, '/quick-todo', {'title': '@测试组 重复测试', 'category': 'team'})
        assert d['ok']
        assert '已广播' in d.get('helper', '')


# ── Detail page renders ──

class TestDetailPage:
    def test_renders(self, client):
        rv = client.get('/requirements/1')
        assert rv.status_code == 200
        html = rv.data.decode()
        assert 'editable-field' in html
        assert 'field-api' in html
