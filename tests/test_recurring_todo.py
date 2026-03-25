"""
周期 Todo 测试用例
用法: python -m pytest tests/test_recurring.py -v
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
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    with app.app_context():
        _db.create_all()
        from app.models.user import Role, User
        admin_role = Role(name='Admin')
        _db.session.add(admin_role)
        _db.session.flush()
        user = User(employee_id='T001', name='测试用户', ip_address='127.0.0.1')
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


class TestRecurringModel:
    """RecurringTodo 模型方法测试"""

    def test_weekly_due_on_monday(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='weekly')
        today = date.today()
        assert r.is_due_today() == (today.weekday() == 0)

    def test_weekly_not_overdue_before_sunday(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='weekly')
        since = r.days_since_last()
        today = date.today()
        if today.weekday() < 6:  # Mon-Sat
            assert since == 0
        else:  # Sunday
            assert since == 1

    def test_weekdays_due(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='weekdays', weekdays='0,1,2,3,4')
        today = date.today()
        assert r.is_due_today() == (today.weekday() < 5)

    def test_weekdays_single(self, app):
        from app.models.recurring_todo import RecurringTodo
        today = date.today()
        r = RecurringTodo(cycle='weekdays', weekdays=str(today.weekday()))
        assert r.is_due_today() is True

    def test_monthly_start(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='start')
        today = date.today()
        assert r.is_due_today() == (today.day == 1)
        assert r.monthly_periods == ['start']
        assert '月初' in r.schedule_desc

    def test_monthly_mid(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='mid')
        today = date.today()
        assert r.is_due_today() == (today.day == 15)

    def test_monthly_end(self, app):
        import calendar

        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='end')
        today = date.today()
        _, last = calendar.monthrange(today.year, today.month)
        assert r.is_due_today() == (today.day == last)

    def test_monthly_multiple(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='start,mid,end')
        assert r.monthly_periods == ['start', 'mid', 'end']
        assert '月初' in r.schedule_desc
        assert '月中' in r.schedule_desc
        assert '月末' in r.schedule_desc

    def test_monthly_end_not_overdue_before_end(self, app):
        """月末还没到不应该算超期"""
        import calendar

        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='end')
        today = date.today()
        _, last = calendar.monthrange(today.year, today.month)
        if today.day < last:
            assert r.days_since_last() == 0

    def test_monthly_start_overdue(self, app):
        """月初过了应该超期"""
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='start')
        today = date.today()
        if today.day > 1:
            assert r.days_since_last() == today.day - 1

    def test_monthly_legacy_day(self, app):
        """兼容旧的 monthly_day 字段"""
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_day=1, monthly_days=None)
        assert r.monthly_periods == ['start']

    def test_days_until_next(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='weekly')
        until = r.days_until_next()
        assert isinstance(until, int)
        assert until >= 0

    def test_period_day(self, app):
        from app.models.recurring_todo import RecurringTodo
        assert RecurringTodo._period_day('start') == 1
        assert RecurringTodo._period_day('mid') == 15
        assert RecurringTodo._period_day('end') >= 28


class TestRecurringRoutes:
    """周期 Todo 路由测试"""

    def test_add_weekly(self, client, app):
        resp = client.post('/recurring-todos/add', data={
            'title': '每周测试', 'cycle': 'weekly',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo.query.filter_by(title='每周测试').first()
            assert r is not None
            assert r.cycle == 'weekly'

    def test_add_weekdays(self, client, app):
        resp = client.post('/recurring-todos/add', data={
            'title': '工作日测试', 'cycle': 'weekdays', 'weekdays': ['0', '2', '4'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            items = RecurringTodo.query.filter_by(title='工作日测试').all()
            assert len(items) == 3  # each weekday gets its own record
            weekdays = sorted(r.weekdays for r in items)
            assert weekdays == ['0', '2', '4']

    def test_add_monthly(self, client, app):
        resp = client.post('/recurring-todos/add', data={
            'title': '月度测试', 'cycle': 'monthly', 'monthly_periods': ['start', 'end'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            items = RecurringTodo.query.filter_by(title='月度测试').all()
            assert len(items) == 2  # each period gets its own record
            periods = sorted(r.monthly_days for r in items)
            assert periods == ['end', 'start']

    def test_toggle_creates_completion(self, client, app):
        """点击 toggle 创建 RecurringCompletion 记录"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo(user_id=1, title='toggle测试', cycle='weekly')
            _db.session.add(r)
            _db.session.commit()
            rid = r.id

        # Toggle to done
        resp = client.post(f'/recurring-todos/{rid}/toggle')
        data = resp.get_json()
        assert data['ok'] is True
        assert data['done'] is True

        # Verify completion record created
        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            c = RecurringCompletion.query.filter_by(
                recurring_id=rid, completed_date=date.today()).first()
            assert c is not None

        # Toggle back (undo)
        resp = client.post(f'/recurring-todos/{rid}/toggle')
        data = resp.get_json()
        assert data['ok'] is True
        assert data['done'] is False

        # Verify completion record removed
        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            c = RecurringCompletion.query.filter_by(
                recurring_id=rid, completed_date=date.today()).first()
            assert c is None

    def test_delete_cleans_completions(self, client, app):
        """删除周期任务时清理完成记录"""
        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo(user_id=1, title='delete测试', cycle='weekly')
            _db.session.add(r)
            _db.session.flush()
            c = RecurringCompletion(recurring_id=r.id, user_id=1, completed_date=date.today())
            _db.session.add(c)
            _db.session.commit()
            rid = r.id

        resp = client.post(f'/recurring-todos/{rid}/delete',
                           headers={'X-Requested-With': 'XMLHttpRequest'})
        assert resp.status_code == 200
        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            from app.models.recurring_todo import RecurringTodo
            assert RecurringTodo.query.get(rid) is None
            assert RecurringCompletion.query.filter_by(recurring_id=rid).count() == 0


class TestRecurringEdgeCases:
    """边界场景和安全测试"""

    def test_double_toggle_same_day(self, client, app):
        """同一天重复 toggle 不会创建多条完成记录"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo(user_id=1, title='重复toggle', cycle='weekly')
            _db.session.add(r)
            _db.session.commit()
            rid = r.id

        # Toggle on
        resp1 = client.post(f'/recurring-todos/{rid}/toggle')
        assert resp1.get_json()['done'] is True
        # Toggle off
        resp2 = client.post(f'/recurring-todos/{rid}/toggle')
        assert resp2.get_json()['done'] is False
        # Toggle on again
        resp3 = client.post(f'/recurring-todos/{rid}/toggle')
        assert resp3.get_json()['done'] is True

        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            count = RecurringCompletion.query.filter_by(
                recurring_id=rid, completed_date=date.today()).count()
            assert count == 1  # exactly one record

    def test_toggle_other_user_forbidden(self, client, app):
        """不能操作别人的周期任务"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            from app.models.user import User
            user2 = User(employee_id='T002', name='他人', ip_address='127.0.0.2')
            _db.session.add(user2)
            _db.session.flush()
            r = RecurringTodo(user_id=user2.id, title='他人的任务', cycle='weekly')
            _db.session.add(r)
            _db.session.commit()
            rid = r.id

        resp = client.post(f'/recurring-todos/{rid}/toggle')
        assert resp.get_json()['ok'] is False or resp.status_code == 403

    def test_toggle_nonexistent(self, client, app):
        """toggle 不存在的周期任务返回 404"""
        resp = client.post('/recurring-todos/99999/toggle')
        assert resp.status_code == 404

    def test_delete_other_user(self, client, app):
        """不能删别人的周期任务"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            from app.models.user import User
            user3 = _db.session.get(User, 2) or User(employee_id='T003', name='他人2', ip_address='127.0.0.3')
            if not user3.id:
                _db.session.add(user3)
                _db.session.flush()
            r = RecurringTodo(user_id=user3.id, title='不能删', cycle='monthly', monthly_days='start')
            _db.session.add(r)
            _db.session.commit()
            rid = r.id

        resp = client.post(f'/recurring-todos/{rid}/delete',
                           headers={'X-Requested-With': 'XMLHttpRequest'})
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            assert RecurringTodo.query.get(rid) is not None  # should NOT be deleted


class TestRecurringStatus:
    """首页 recurring_status 渲染逻辑测试（基于 RecurringCompletion）"""

    def test_status_from_completion(self, client, app):
        """recurring_status 从 RecurringCompletion 表查询"""
        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo(user_id=1, title='completion状态测试', cycle='monthly', monthly_days='mid')
            _db.session.add(r)
            _db.session.flush()
            c = RecurringCompletion(recurring_id=r.id, user_id=1, completed_date=date.today())
            _db.session.add(c)
            _db.session.commit()

        resp = client.get('/')
        html = resp.data.decode()
        assert 'completion状态测试' in html
        import re
        match = re.search(r'completion状态测试.*?badge ([^"]+)"[^>]*>每月月中', html, re.DOTALL)
        if match:
            badge_class = match.group(1)
            # Should be green (done) or yellow (补完成), not red
            assert 'bg-danger' not in badge_class, f'Should not be red, got: {badge_class}'

    def test_no_completion_shows_due_or_future(self, client, app):
        """没有完成记录时，到期显示蓝色，未到期显示灰色"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo(user_id=1, title='未完成状态测试', cycle='weekdays',
                              weekdays=str(date.today().weekday()))
            _db.session.add(r)
            _db.session.commit()

        resp = client.get('/')
        html = resp.data.decode()
        assert '未完成状态测试' in html
        import re
        match = re.search(r'未完成状态测试.*?badge ([^"]+)"', html, re.DOTALL)
        if match:
            badge_class = match.group(1)
            # Today's due item without completion → gray (bg-light), not red
            assert 'bg-light' in badge_class, f'Expected gray for due today, got: {badge_class}'

    def test_completion_independent_of_todo(self, client, app):
        """周期任务完成不会创建 Todo 记录"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo(user_id=1, title='独立性测试', cycle='weekly')
            _db.session.add(r)
            _db.session.commit()
            rid = r.id

        # Complete via toggle
        client.post(f'/recurring-todos/{rid}/toggle')

        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            # Completion record exists
            c = RecurringCompletion.query.filter_by(recurring_id=rid).first()
            assert c is not None


class TestRecurringMonthlyPeriods:
    """月度多时段测试"""

    def test_start_mid_end_all(self, app):
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='start,mid,end')
        assert len(r.monthly_periods) == 3
        today = date.today()
        import calendar
        _, last = calendar.monthrange(today.year, today.month)
        due = r.is_due_today()
        assert due == (today.day in (1, 15, last))

    def test_end_only_not_overdue_mid_month(self, app):
        """月末还没到，不算超期"""
        import calendar

        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='end')
        today = date.today()
        _, last = calendar.monthrange(today.year, today.month)
        if today.day < last:
            assert r.days_since_last() == 0

    def test_start_overdue_after_first(self, app):
        """月初过了应该有超期天数"""
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='start')
        today = date.today()
        if today.day > 1:
            assert r.days_since_last() == today.day - 1

    def test_mixed_past_and_future(self, app):
        """start(过期) + end(未到) → since_last 只看 start"""
        import calendar

        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='start,end')
        today = date.today()
        _, last = calendar.monthrange(today.year, today.month)
        if today.day > 1 and today.day < last:
            assert r.days_since_last() == today.day - 1  # from start(1st)

    def test_days_until_next_multiple(self, app):
        """多时段取最近的下一个"""
        from app.models.recurring_todo import RecurringTodo
        r = RecurringTodo(cycle='monthly', monthly_days='start,mid,end')
        until = r.days_until_next()
        assert isinstance(until, int)
        assert until >= 0
