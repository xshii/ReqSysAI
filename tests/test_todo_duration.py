"""
Todo 时长缩写解析测试：末尾输入 2h/3d/1w 自动设置 due_date
用法: python -m pytest tests/test_todo_duration.py -v
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


class TestDurationSuffix:
    """末尾时长缩写 → due_date 解析"""

    def test_hours_sets_today(self, client, app):
        """2h → due_date = today, title 不含 '2h'"""
        resp = client.post('/quick-todo', json={'title': '修复登录bug 2h', 'category': 'team'})
        data = resp.get_json()
        assert data['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, data['todo_id'])
            assert t.title == '修复登录bug'
            assert t.due_date == date.today()

    def test_days_sets_future(self, client, app):
        """3d → due_date = today + 3"""
        resp = client.post('/quick-todo', json={'title': '完成API对接 3d', 'category': 'team'})
        data = resp.get_json()
        assert data['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, data['todo_id'])
            assert t.title == '完成API对接'
            assert t.due_date == date.today() + timedelta(days=3)

    def test_weeks_sets_future(self, client, app):
        """1w → due_date = today + 7"""
        resp = client.post('/quick-todo', json={'title': '准备评审材料 1w', 'category': 'team'})
        data = resp.get_json()
        assert data['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, data['todo_id'])
            assert t.title == '准备评审材料'
            assert t.due_date == date.today() + timedelta(weeks=1)

    def test_no_suffix_defaults_today(self, client, app):
        """无缩写 → due_date = today"""
        resp = client.post('/quick-todo', json={'title': '普通任务', 'category': 'team'})
        data = resp.get_json()
        assert data['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, data['todo_id'])
            assert t.title == '普通任务'
            assert t.due_date == date.today()

    def test_suffix_not_in_title(self, client, app):
        """缩写从标题中移除"""
        resp = client.post('/quick-todo', json={'title': '写文档 5d', 'category': 'team'})
        data = resp.get_json()
        assert data['ok']
        assert data['title'] == '写文档'

    def test_suffix_requires_space(self, client, app):
        """缩写前必须有空格：'任务2d' 不解析，'任务 2d' 解析"""
        resp = client.post('/quick-todo', json={'title': '任务2d', 'category': 'team'})
        data = resp.get_json()
        assert data['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, data['todo_id'])
            assert t.title == '任务2d'  # 不解析，保留原文
            assert t.due_date == date.today()

    def test_large_number(self, client, app):
        """30d → today + 30"""
        resp = client.post('/quick-todo', json={'title': '长期规划 30d', 'category': 'team'})
        data = resp.get_json()
        assert data['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, data['todo_id'])
            assert t.due_date == date.today() + timedelta(days=30)

    def test_form_submit(self, client, app):
        """表单提交也支持缩写"""
        resp = client.post('/quick-todo', data={
            'title': '表单任务 2d', 'category': 'team', 'next': '/'
        }, follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            from app.models.todo import Todo
            t = Todo.query.filter_by(title='表单任务').first()
            assert t is not None
            assert t.due_date == date.today() + timedelta(days=2)
