"""
登录页测试用例：IP 自动登录、多 IP 匹配、登出防重登、工号验证
用法: python -m pytest tests/test_login.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import create_app
from app.extensions import db as _db


def _make_app():
    """创建独立 app 避免 session 污染"""
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    with app.app_context():
        _db.create_all()
        from app.models.user import Role, User
        r = Role(name='Admin')
        _db.session.add(r)
        _db.session.flush()
        u1 = User(employee_id='t001', name='用户一', ip_address='192.168.1.100,127.0.0.1')
        u1.roles.append(r)
        _db.session.add(u1)
        u2 = User(employee_id='t002', name='用户二', ip_address='10.0.0.5')
        _db.session.add(u2)
        _db.session.commit()
    return app


def _with_ip(ip, fn):
    """临时设置 DEV_CLIENT_IP 环境变量执行测试"""
    os.environ['DEV_CLIENT_IP'] = ip
    try:
        return fn()
    finally:
        os.environ.pop('DEV_CLIENT_IP', None)


# ─── IP 自动登录 ────────────────────────────────────────────

class TestAutoLoginByIP:
    """IP 自动登录：精确匹配、多 IP、部分匹配防护"""

    def test_exact_ip_match(self):
        """精确 IP 匹配自动登录"""
        def run():
            a = _make_app()
            with a.app_context(), a.test_client() as c:
                resp = c.get('/login')
                assert resp.status_code == 302
        _with_ip('192.168.1.100', run)

    def test_second_ip_match(self):
        """逗号分隔的第二个 IP 也能匹配"""
        def run():
            a = _make_app()
            with a.app_context(), a.test_client() as c:
                assert c.get('/login').status_code == 302
        _with_ip('127.0.0.1', run)

    def test_partial_ip_no_match(self):
        """部分 IP 不应匹配（'10' 不匹配 '10.0.0.5'）"""
        def run():
            a = _make_app()
            with a.app_context(), a.test_client() as c:
                assert c.get('/login').status_code == 200
        _with_ip('10', run)

    def test_similar_ip_no_match(self):
        """相似 IP 不应匹配（'192.168.1.10' 不匹配 '192.168.1.100'）"""
        def run():
            a = _make_app()
            with a.app_context(), a.test_client() as c:
                assert c.get('/login').status_code == 200
        _with_ip('192.168.1.10', run)

    def test_unknown_ip_no_match(self):
        """未知 IP 不自动登录"""
        def run():
            a = _make_app()
            with a.app_context(), a.test_client() as c:
                assert c.get('/login').status_code == 200
        _with_ip('99.99.99.99', run)


# ─── 工号验证 ───────────────────────────────────────────────

class TestLoginValidation:
    """登录表单验证"""

    def test_wrong_eid_clears_input(self):
        """工号错误时清空输入并提示"""
        def run():
            a = _make_app()
            a.config['WTF_CSRF_ENABLED'] = False
            with a.app_context(), a.test_client() as c:
                resp = c.post('/login', data={'employee_id': 'a00999999'})
                assert '工号未注册' in resp.data.decode()
        _with_ip('99.99.99.99', run)


# ─── 登出 ──────────────────────────────────────────────────

class TestLogout:
    """登出 + 防止 IP 自动重登录"""

    @pytest.fixture
    def app(self):
        a = _make_app()
        yield a

    def test_logout_prevents_auto_relogin(self, app):
        """登出后不会被 IP 自动登录"""
        with app.test_client() as c:
            with c.session_transaction() as s:
                s['_user_id'] = '1'
            c.get('/logout')
            resp = c.get('/login', headers={'X-Forwarded-For': '127.0.0.1'})
            assert resp.status_code == 200  # 登录页，未自动登录

    def test_refresh_after_logout_restores_auto_login(self, app):
        """登出后再次刷新恢复自动登录"""
        with app.test_client() as c:
            with c.session_transaction() as s:
                s['_user_id'] = '1'
            c.get('/logout')
            c.get('/login', headers={'X-Forwarded-For': '127.0.0.1'})  # 消耗 flag
            resp = c.get('/login', headers={'X-Forwarded-For': '127.0.0.1'})
            assert resp.status_code == 302  # 自动登录恢复
