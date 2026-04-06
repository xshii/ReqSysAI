"""
喝水功能测试：记录API、统计API、按钮验证
用法: python -m pytest tests/test_water.py -v
"""
import os
import sys
from datetime import date, timedelta

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
        admin_role = Role(name='Admin')
        _db.session.add(admin_role)
        _db.session.flush()
        user = User(employee_id='t001', name='测试用户', ip_address='127.0.0.1')
        user.roles.append(admin_role)
        _db.session.add(user)
        _db.session.commit()
        yield app


@pytest.fixture(autouse=True)
def cleanup(app):
    yield
    with app.app_context():
        from app.models.water_log import WaterLog
        WaterLog.query.delete()
        _db.session.commit()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = '1'
        yield c


class TestWaterLogAPI:
    """POST /api/water-log"""

    def test_250ml(self, client, app):
        resp = client.post('/api/water-log', json={'ml': 250})
        d = resp.get_json()
        assert d['ok']
        assert d['ml'] == 250
        assert d['today_total'] == 250

    def test_500ml(self, client, app):
        resp = client.post('/api/water-log', json={'ml': 500})
        d = resp.get_json()
        assert d['ok']
        assert d['ml'] == 500
        assert d['today_total'] == 500

    def test_750ml(self, client, app):
        resp = client.post('/api/water-log', json={'ml': 750})
        d = resp.get_json()
        assert d['ok']
        assert d['ml'] == 750
        assert d['today_total'] == 750

    def test_invalid_ml_rejected(self, client):
        resp = client.post('/api/water-log', json={'ml': 100})
        d = resp.get_json()
        assert not d['ok']

    def test_accumulates(self, client, app):
        """Multiple drinks accumulate today_total"""
        client.post('/api/water-log', json={'ml': 250})
        client.post('/api/water-log', json={'ml': 500})
        resp = client.post('/api/water-log', json={'ml': 750})
        d = resp.get_json()
        assert d['today_total'] == 1500

    def test_stores_in_db(self, client, app):
        client.post('/api/water-log', json={'ml': 500})
        with app.app_context():
            from app.models.water_log import WaterLog
            logs = WaterLog.query.filter_by(user_id=1, date=date.today()).all()
            assert len(logs) == 1
            assert logs[0].ml == 500


class TestWaterStatsAPI:
    """GET /api/water-stats"""

    def test_empty(self, client):
        resp = client.get('/api/water-stats')
        d = resp.get_json()
        assert d['ok']
        assert d['today'] == 0
        assert len(d['days']) <= 7
        assert all(day['ml'] == 0 for day in d['days'])

    def test_today_total(self, client):
        client.post('/api/water-log', json={'ml': 250})
        client.post('/api/water-log', json={'ml': 500})
        resp = client.get('/api/water-stats')
        d = resp.get_json()
        assert d['today'] == 750

    def test_week_data(self, client, app):
        """Stats include past days"""
        with app.app_context():
            from app.models.water_log import WaterLog
            yesterday = date.today() - timedelta(days=1)
            _db.session.add(WaterLog(user_id=1, ml=750, date=yesterday))
            _db.session.commit()
        resp = client.get('/api/water-stats')
        d = resp.get_json()
        yesterday_str = str(date.today() - timedelta(days=1))
        found = [day for day in d['days'] if day['date'] == yesterday_str]
        assert len(found) == 1
        assert found[0]['ml'] == 750

    def test_days_ordered(self, client):
        """Days are in chronological order"""
        resp = client.get('/api/water-stats')
        d = resp.get_json()
        dates = [day['date'] for day in d['days']]
        assert dates == sorted(dates)


class TestWaterHomepage:
    """Homepage shows water visualization"""

    def test_homepage_has_droplet_icon(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert 'bi-droplet-fill' in resp.get_data(as_text=True)

    def test_homepage_shows_week_total(self, client):
        client.post('/api/water-log', json={'ml': 500})
        resp = client.get('/')
        html = resp.get_data(as_text=True)
        assert '0.5L' in html  # 500ml = 0.5L
