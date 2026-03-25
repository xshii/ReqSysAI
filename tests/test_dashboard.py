"""
数据看板测试用例 (dashboard/)
用法: python -m pytest tests/test_dashboard.py -v
"""
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
        from app.models.user import Role, User
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


# ─── 页面加载 ───────────────────────────────────────────────

class TestDashboardPages:
    """看板各页面正常加载"""

    def test_requirement_progress(self, client):
        assert client.get('/dashboard/requirements').status_code == 200

    def test_stats(self, client):
        assert client.get('/dashboard/stats').status_code == 200

    def test_metrics(self, client):
        assert client.get('/dashboard/metrics').status_code == 200

    def test_weekly_report(self, client):
        assert client.get('/dashboard/weekly-report').status_code == 200

    def test_my_weekly(self, client):
        assert client.get('/dashboard/my-weekly').status_code == 200

    def test_resource_map(self, client):
        assert client.get('/dashboard/resource-map').status_code == 200

    def test_emotion(self, client):
        assert client.get('/dashboard/emotion').status_code == 200
