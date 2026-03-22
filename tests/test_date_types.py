"""
Date 类型安全测试 — 确保所有接受日期的路由正确转换字符串为 date 对象。
用法: python -m pytest tests/test_date_types.py -v
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope='module')
def app():
    app = create_app('testing')
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'  # in-memory
    with app.app_context():
        _db.create_all()
        # Seed minimal data
        from app.models.user import User, Role
        from app.models.project import Project
        from app.models.requirement import Requirement
        admin_role = Role(name='Admin')
        _db.session.add(admin_role)
        _db.session.flush()
        user = User(employee_id='T001', name='测试用户', ip_address='127.0.0.1')
        user.roles.append(admin_role)
        _db.session.add(user)
        _db.session.flush()
        project = Project(name='测试项目', created_by=user.id)
        _db.session.add(project)
        _db.session.flush()
        req = Requirement(project_id=project.id, title='测试需求', number='REQ-T01',
                          status='open', priority='medium', created_by=user.id)
        _db.session.add(req)
        _db.session.commit()
        yield app


@pytest.fixture(autouse=True)
def rollback_after_test(app):
    """Ensure clean session between tests."""
    yield
    with app.app_context():
        _db.session.rollback()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['_user_id'] = '1'
        yield c


class TestMilestoneDateConversion:
    """项目创建时里程碑日期字符串 → date 对象"""

    def test_create_project_with_milestone_date(self, client):
        resp = client.post('/projects/new', data={
            'name': '日期测试项目',
            'parent_id': 0,
            'description': '',
            'ms_name': ['里程碑1', '里程碑2'],
            'ms_date': ['2026-06-01', '2026-07-01'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        from app.models.project import Milestone
        ms = Milestone.query.filter_by(name='里程碑1').first()
        assert ms is not None
        assert isinstance(ms.due_date, date)
        assert ms.due_date == date(2026, 6, 1)

    def test_create_project_with_empty_milestone_date(self, client):
        resp = client.post('/projects/new', data={
            'name': '空日期项目',
            'parent_id': 0,
            'description': '',
            'ms_name': ['无日期里程碑'],
            'ms_date': [''],
        }, follow_redirects=True)
        assert resp.status_code == 200
        from app.models.project import Milestone
        ms = Milestone.query.filter_by(name='无日期里程碑').first()
        assert ms is not None
        assert ms.due_date is None


class TestRiskDateConversion:
    """风险创建时 due_date 字符串 → date 对象"""

    def test_create_risk_with_date(self, client):
        resp = client.post('/projects/1/risks/add', data={
            'title': '日期测试风险',
            'severity': 'high',
            'due_date': '2026-05-15',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from app.models.risk import Risk
        risk = Risk.query.filter_by(title='日期测试风险').first()
        assert risk is not None
        assert isinstance(risk.due_date, date)
        assert risk.due_date == date(2026, 5, 15)

    def test_create_risk_with_another_date(self, client):
        """Risk.due_date is NOT NULL, so always requires a date."""
        resp = client.post('/projects/1/risks/add', data={
            'title': '另一个风险',
            'severity': 'medium',
            'due_date': '2026-12-31',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from app.models.risk import Risk
        risk = Risk.query.filter_by(title='另一个风险').first()
        assert risk is not None
        assert isinstance(risk.due_date, date)
        assert risk.due_date == date(2026, 12, 31)


class TestTodoDateConversion:
    """Todo due_date 字符串 → date 对象"""

    def test_edit_todo_with_date(self, client, app):
        # Create a todo first
        from app.models.todo import Todo
        with app.app_context():
            todo = Todo(user_id=1, title='日期测试todo', created_date=date.today())
            _db.session.add(todo)
            _db.session.commit()
            todo_id = todo.id

        resp = client.post(f'/todos/{todo_id}/edit',
                           json={'title': '修改后', 'due_date': '2026-08-01'})
        assert resp.status_code == 200
        with app.app_context():
            todo = _db.session.get(Todo, todo_id)
            assert isinstance(todo.due_date, date)
            assert todo.due_date == date(2026, 8, 1)

    def test_edit_todo_clear_date(self, client, app):
        from app.models.todo import Todo
        with app.app_context():
            todo = Todo(user_id=1, title='清除日期', created_date=date.today(),
                        due_date=date(2026, 1, 1))
            _db.session.add(todo)
            _db.session.commit()
            todo_id = todo.id

        resp = client.post(f'/todos/{todo_id}/edit',
                           json={'title': '清除日期', 'due_date': ''})
        assert resp.status_code == 200
        with app.app_context():
            todo = _db.session.get(Todo, todo_id)
            assert todo.due_date is None


class TestWeeklyReportDateConversion:
    """周报保存/冻结时 week_start 字符串 → date 对象"""

    def test_weekly_report_save(self, client, app):
        # Create a saved report first
        from app.models.report import WeeklyReport
        with app.app_context():
            wr = WeeklyReport(project_id=1, week_start=date(2026, 3, 16),
                              week_end=date(2026, 3, 22), summary='test', created_by=1)
            _db.session.add(wr)
            _db.session.commit()

        resp = client.post('/dashboard/weekly-report/save', data={
            'project_id': 1,
            'week_start': '2026-03-16',
            'offset': 0,
            'summary': '更新后的进展',
            'risks': '风险1',
            'plan': '计划1',
        }, follow_redirects=True)
        assert resp.status_code == 200
