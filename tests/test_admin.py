"""
管理后台测试用例 (admin/)
用法: python -m pytest tests/test_admin.py -v
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
        admin_role = Role(name='Admin')
        pm_role = Role(name='PM')
        _db.session.add_all([admin_role, pm_role])
        _db.session.flush()
        u = User(employee_id='a00000001', name='管理员', ip_address='127.0.0.1')
        u.roles.append(admin_role)
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


# ─── 用户管理 ───────────────────────────────────────────────

class TestUserManagement:
    """用户增删改查"""

    def test_user_list_page(self, client):
        resp = client.get('/admin/users')
        assert resp.status_code == 200
        assert '管理员' in resp.data.decode()

    def test_create_user_page_loads(self, client):
        """创建用户页面正常加载"""
        resp = client.get('/admin/users/new')
        assert resp.status_code == 200
        assert '创建用户' in resp.data.decode()

    def test_delete_user(self, client, app):
        with app.app_context():
            from app.models.user import User
            u = User(employee_id='a00100098', name='要删', ip_address='pending-a00100098')
            _db.session.add(u)
            _db.session.commit()
            uid = u.id
        resp = client.post(f'/admin/users/{uid}/delete', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.user import User
            assert _db.session.get(User, uid) is None


# ─── CSV 导入 ───────────────────────────────────────────────

class TestCSVImport:
    """CSV 用户导入（支持特殊角色）"""

    def test_import_with_admin_role(self, client, app):
        import io
        csv = 'id,工号,姓名,团队,角色\n,a00200001,CSV用户,开发组,Admin'
        data = {'csv_file': (io.BytesIO(csv.encode('utf-8')), 'users.csv')}
        resp = client.post('/admin/users/import-csv', data=data,
                           content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.user import User
            u = User.query.filter_by(employee_id='a00200001').first()
            assert u is not None
            assert any(r.name == 'Admin' for r in u.roles)


# ─── 团队管理 ───────────────────────────────────────────────

class TestGroupManagement:
    """团队增删"""

    def test_create_group(self, client, app):
        resp = client.post('/admin/groups/action', data={
            'action': 'create', 'name': '测试组',
        }, follow_redirects=True)
        # May flash success or already exists
        assert resp.status_code == 200
