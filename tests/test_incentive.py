"""
激励系统测试用例 (incentive/)
用法: python -m pytest tests/test_incentive.py -v
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
        u2 = User(employee_id='a00100001', name='被提名者', ip_address='127.0.0.2')
        _db.session.add(u2)
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


# ─── 激励页面 ───────────────────────────────────────────────

class TestIncentivePage:
    """激励系统基本操作"""

    def test_index_page(self, client):
        resp = client.get('/incentive/')
        assert resp.status_code == 200

    def test_submit_incentive(self, client, app):
        resp = client.post('/incentive/submit', data={
            'title': '技术突破奖',
            'category': '技术突破',
            'description': '完成了关键性能优化',
            'nominees': '2',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_like_incentive(self, client, app):
        with app.app_context():
            from app.models.incentive import Incentive
            inc = Incentive(title='点赞测试', category='协作',
                            description='测试', submitted_by=1,
                            status='approved')
            _db.session.add(inc)
            _db.session.commit()
            inc_id = inc.id
        resp = client.post(f'/incentive/{inc_id}/like',
                           headers={'X-Requested-With': 'XMLHttpRequest'})
        # May return JSON or redirect depending on implementation
        if resp.content_type and 'json' in resp.content_type:
            data = resp.get_json()
            assert data['ok'] is True
        else:
            assert resp.status_code in (200, 302)
