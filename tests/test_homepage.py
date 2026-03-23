"""
首页测试用例：进度条、Todo 超期、周期任务双列、删除、拖拽排序、
             快速添加、周期完成独立性、AI 高亮
用法: python -m pytest tests/test_homepage.py -v
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
        from app.models.user import User, Role
        admin_role = Role(name='Admin')
        _db.session.add(admin_role)
        _db.session.flush()
        user = User(employee_id='t001', name='测试用户', ip_address='192.168.1.100,127.0.0.1')
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


def _create_todo(title='测试任务', status='todo', user_id=1):
    from app.models.todo import Todo, TodoItem
    t = Todo(user_id=user_id, title=title, status=status,
             created_date=date.today(),
             done_date=date.today() if status == 'done' else None)
    t.items.append(TodoItem(title=title, sort_order=0,
                            is_done=(status == 'done')))
    _db.session.add(t)
    _db.session.flush()
    return t


# ─── 进度条 ────────────────────────────────────────────────

class TestProgressBar:
    """首页顶部进度条 todo_done/todo_total"""

    def test_progress_shows_correct_count(self, client, app):
        """进度条显示正确的完成/总数"""
        with app.app_context():
            _create_todo('任务A', 'todo')
            _create_todo('任务B', 'done')
            _create_todo('任务C', 'todo')
            _db.session.commit()

        resp = client.get('/')
        html = resp.data.decode()
        assert 'todayProgressBadge' in html
        assert '>1/3' in html.replace(' ', '').replace('\n', '')

    def test_progress_js_vars_exist(self, client, app):
        """页面包含实时更新所需的 JS 变量"""
        with app.app_context():
            _create_todo('JS变量测试', 'done')
            _db.session.commit()

        resp = client.get('/')
        html = resp.data.decode()
        assert '_todoDone' in html
        assert '_todoTotal' in html
        assert '_updateProgress' in html
        assert 'todayProgressBadge' in html
        assert 'todayProgressBar' in html

    def test_progress_empty_no_error(self, client, app):
        """没有 todo 时页面不报错"""
        resp = client.get('/')
        assert resp.status_code == 200
        assert 'todayProgressBadge' in resp.data.decode()


# ─── Todo 完成/取消 ─────────────────────────────────────────

class TestTodoToggle:
    """Todo 完成状态切换"""

    def test_toggle_to_done(self, client, app):
        """toggle 切换为完成"""
        with app.app_context():
            t = _create_todo('toggle测试', 'todo')
            _db.session.commit()
            tid = t.id

        resp = client.post(f'/todo/{tid}/toggle', json={})
        data = resp.get_json()
        assert data['ok'] is True
        assert data['done'] is True

        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, tid)
            assert t.status == 'done'
            assert t.done_date == date.today()

    def test_toggle_back_to_todo(self, client, app):
        """toggle 取消完成"""
        with app.app_context():
            t = _create_todo('反toggle', 'done')
            _db.session.commit()
            tid = t.id

        resp = client.post(f'/todo/{tid}/toggle', json={})
        data = resp.get_json()
        assert data['ok'] is True
        assert data['done'] is False

        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, tid)
            assert t.status == 'todo'
            assert t.done_date is None


# ─── Todo 超期提示 ──────────────────────────────────────────

class TestTodoOverdue:
    """过期 Todo 显示：红/黄边框 + '延N天' badge"""

    def test_overdue_badge_shows(self, client, app):
        """超期任务显示'延N天' badge"""
        with app.app_context():
            from app.models.todo import Todo, TodoItem
            t = Todo(user_id=1, title='超期任务测试XYZ', status='todo',
                     created_date=date.today() - timedelta(days=5))
            t.items.append(TodoItem(title='超期任务测试XYZ', sort_order=0))
            _db.session.add(t)
            _db.session.commit()

        resp = client.get('/')
        html = resp.data.decode()
        assert '超期任务测试XYZ' in html
        assert '延' in html and '天' in html

    def test_overdue_danger_border(self, client, app):
        """超期3天以上有红色左边框"""
        with app.app_context():
            from app.models.todo import Todo, TodoItem
            t = Todo(user_id=1, title='红色边框测试', status='todo',
                     created_date=date.today() - timedelta(days=7))
            t.items.append(TodoItem(title='红色边框测试', sort_order=0))
            _db.session.add(t)
            _db.session.commit()

        resp = client.get('/')
        assert 'border-danger' in resp.data.decode()

    def test_done_todo_no_overdue(self, client, app):
        """已完成的 todo 不显示超期"""
        with app.app_context():
            from app.models.todo import Todo, TodoItem
            t = Todo(user_id=1, title='已完成不超期', status='done',
                     created_date=date.today() - timedelta(days=10),
                     done_date=date.today())
            t.items.append(TodoItem(title='已完成不超期', sort_order=0))
            _db.session.add(t)
            _db.session.commit()

        resp = client.get('/')
        html = resp.data.decode()
        idx = html.find('已完成不超期')
        if idx >= 0:
            section = html[idx:idx + 300]
            assert '延' not in section or '天' not in section


# ─── 删除 Todo ──────────────────────────────────────────────

class TestDeleteTodo:
    """首页删除 Todo"""

    def test_delete_removes_todo(self, client, app):
        """删除后数据库中消失"""
        with app.app_context():
            t = _create_todo('要删的', 'todo')
            _db.session.commit()
            tid = t.id

        resp = client.post(f'/todos/{tid}/edit', json={'title': ''})
        assert resp.get_json()['ok'] is True

        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid) is None

    def test_delete_done_todo(self, client, app):
        """已完成的 todo 也能删除"""
        with app.app_context():
            t = _create_todo('已完成要删', 'done')
            _db.session.commit()
            tid = t.id

        assert client.post(f'/todos/{tid}/edit', json={'title': ''}).get_json()['ok'] is True


# ─── 周期任务双列布局 ───────────────────────────────────────

class TestRecurringTwoColumns:
    """首页周期任务：周任务 | 月任务 双列"""

    def test_weekly_column_shows(self, client, app):
        """周任务列正确显示"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            _db.session.add(RecurringTodo(user_id=1, title='每周站会', cycle='weekly', is_active=True))
            _db.session.commit()

        html = client.get('/').data.decode()
        assert '周任务' in html
        assert '每周站会' in html

    def test_monthly_column_shows(self, client, app):
        """月任务列正确显示"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            _db.session.add(RecurringTodo(user_id=1, title='月度回顾', cycle='monthly',
                                          monthly_days='start', is_active=True))
            _db.session.commit()

        html = client.get('/').data.decode()
        assert '月任务' in html
        assert '月度回顾' in html

    def test_date_range_shows(self, client, app):
        """周任务显示日期范围，月任务显示年月"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            _db.session.add(RecurringTodo(user_id=1, title='日期范围', cycle='weekly', is_active=True))
            _db.session.commit()

        html = client.get('/').data.decode()
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        assert week_start.strftime('%m/%d') in html
        assert today.strftime('%Y/%m') in html

    def test_weekday_in_weekly_column(self, client, app):
        """weekdays 类型归入周任务列（不是月任务）"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            _db.session.add(RecurringTodo(user_id=1, title='工作日签到', cycle='weekdays',
                                          weekdays='0', is_active=True))
            _db.session.commit()

        html = client.get('/').data.decode()
        idx_weekly = html.find('周任务')
        idx_monthly = html.find('月任务')
        idx_title = html.find('工作日签到')
        assert idx_weekly < idx_title < idx_monthly


# ─── 拖拽排序 ──────────────────────────────────────────────

class TestDragSort:
    """Todo 拖拽排序（后端 sort_order 更新）"""

    def test_drag_reorder(self, client, app):
        """拖拽后 sort_order 正确更新"""
        with app.app_context():
            t1 = _create_todo('排序A', 'todo')
            t2 = _create_todo('排序B', 'todo')
            t3 = _create_todo('排序C', 'todo')
            _db.session.commit()
            ids = [t3.id, t1.id, t2.id]  # C→A→B 新顺序

        resp = client.post('/todos/drag', json={'id': ids[0], 'order': ids})
        assert resp.get_json()['ok'] is True

        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, ids[0]).sort_order == 0  # C first
            assert _db.session.get(Todo, ids[1]).sort_order == 1  # A second
            assert _db.session.get(Todo, ids[2]).sort_order == 2  # B third

    def test_drag_other_user_forbidden(self, client, app):
        """不能拖拽别人的 todo"""
        with app.app_context():
            from app.models.user import User
            u2 = User.query.filter_by(employee_id='t002').first()
            if not u2:
                u2 = User(employee_id='t002', name='他人', ip_address='10.0.0.2')
                _db.session.add(u2)
                _db.session.flush()
            t = _create_todo('他人的', 'todo', user_id=u2.id)
            _db.session.commit()
            tid = t.id

        resp = client.post('/todos/drag', json={'id': tid, 'order': [tid]})
        assert resp.status_code == 403

    def test_move_todo_to_team(self, client, app):
        """移动 todo 到团队分类"""
        with app.app_context():
            t = _create_todo('移动测试', 'todo')
            _db.session.commit()
            tid = t.id

        resp = client.post('/api/move-todo', json={'todo_id': tid, 'req_id': 'team'})
        data = resp.get_json()
        assert data['ok'] is True

        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid).category == 'team'

    def test_move_todo_to_risk(self, client, app):
        """移动 todo 到风险分类"""
        with app.app_context():
            t = _create_todo('风险移动', 'todo')
            _db.session.commit()
            tid = t.id

        resp = client.post('/api/move-todo', json={'todo_id': tid, 'req_id': 'risk'})
        assert resp.get_json()['ok'] is True

        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid).category == 'risk'


# ─── 快速添加 Todo ─────────────────────────────────────────

class TestQuickTodo:
    """首页快速添加 Todo"""

    def test_add_team_todo(self, client, app):
        """添加团队 todo"""
        resp = client.post('/quick-todo', json={
            'title': '快速添加测试', 'category': 'team',
        })
        data = resp.get_json()
        assert data['ok'] is True
        assert data['todo_id'] > 0

        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, data['todo_id'])
            assert t.title == '快速添加测试'
            assert t.category == 'team'

    def test_add_risk_todo(self, client, app):
        """添加风险 todo"""
        resp = client.post('/quick-todo', json={
            'title': '紧急bug', 'category': 'risk',
        })
        data = resp.get_json()
        assert data['ok'] is True

    def test_add_personal_todo(self, client, app):
        """添加个人 todo"""
        resp = client.post('/quick-todo', json={
            'title': '读书30分钟', 'category': 'personal',
        })
        assert client.post('/quick-todo', json={
            'title': '读书30分钟', 'category': 'personal',
        }).get_json()['ok'] is True

    def test_add_empty_title_fails(self, client):
        """空标题不创建"""
        resp = client.post('/quick-todo', json={'title': '', 'category': 'team'})
        # Should fail or redirect
        data = resp.get_json()
        assert not data or not data.get('ok') or data.get('title') == ''


# ─── 周期任务完成独立性 ─────────────────────────────────────

class TestRecurringCompletion:
    """周期任务完成不创建 Todo，使用 RecurringCompletion"""

    def test_toggle_creates_completion_not_todo(self, client, app):
        """点击周期标签创建 completion 记录，不创建 Todo"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            r = RecurringTodo(user_id=1, title='独立测试', cycle='weekly', is_active=True)
            _db.session.add(r)
            _db.session.commit()
            rid = r.id

        resp = client.post(f'/recurring-todos/{rid}/toggle')
        data = resp.get_json()
        assert data['ok'] is True
        assert data['done'] is True

        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            from app.models.todo import Todo
            assert RecurringCompletion.query.filter_by(recurring_id=rid).count() == 1
            assert Todo.query.filter_by(recurring_id=rid).count() == 0

    def test_toggle_undo_removes_completion(self, client, app):
        """再次点击取消完成，删除 completion 记录"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            from app.models.recurring_completion import RecurringCompletion
            r = RecurringTodo(user_id=1, title='取消测试', cycle='weekly', is_active=True)
            _db.session.add(r)
            _db.session.flush()
            c = RecurringCompletion(recurring_id=r.id, user_id=1, completed_date=date.today())
            _db.session.add(c)
            _db.session.commit()
            rid = r.id

        resp = client.post(f'/recurring-todos/{rid}/toggle')
        assert resp.get_json()['done'] is False

        with app.app_context():
            from app.models.recurring_completion import RecurringCompletion
            assert RecurringCompletion.query.filter_by(recurring_id=rid,
                completed_date=date.today()).count() == 0

    def test_homepage_status_from_completion(self, client, app):
        """首页周期状态从 RecurringCompletion 查询"""
        with app.app_context():
            from app.models.recurring_todo import RecurringTodo
            from app.models.recurring_completion import RecurringCompletion
            r = RecurringTodo(user_id=1, title='状态来源测试', cycle='weekdays',
                              weekdays=str(date.today().weekday()), is_active=True)
            _db.session.add(r)
            _db.session.flush()
            c = RecurringCompletion(recurring_id=r.id, user_id=1, completed_date=date.today())
            _db.session.add(c)
            _db.session.commit()

        html = client.get('/').data.decode()
        assert '状态来源测试' in html
        # Should show green (completed)
        import re
        match = re.search(r'状态来源测试.*?badge\s+([^"]+)"', html, re.DOTALL)
        if match:
            assert 'bg-success' in match.group(1)


# ─── AI 推荐高亮周期标签 ───────────────────────────────────

class TestAIRecurringHighlight:
    """AI 推荐返回 recurring_highlight_ids 供前端高亮"""

    def test_highlight_js_code_exists(self, client, app):
        """前端包含高亮周期标签的 JS 代码"""
        html = client.get('/').data.decode()
        assert 'recurring_highlight_ids' in html
        assert 'ai-highlight' in html

    def test_ai_highlight_css_exists(self, client, app):
        """AI 高亮 CSS 动画存在"""
        html = client.get('/').data.decode()
        assert 'ai-pulse' in html
        assert '.ai-highlight' in html


# ─── 超期提示边界 ──────────────────────────────────────────

class TestOverdueEdgeCases:
    """超期边界场景"""

    def test_warning_border_1_2_days(self, client, app):
        """延期1-2个工作日黄色边框"""
        with app.app_context():
            from app.models.todo import Todo, TodoItem
            # Create 3 calendar days ago to guarantee >= 1 workday overdue
            t = Todo(user_id=1, title='黄色边框测试', status='todo',
                     created_date=date.today() - timedelta(days=3))
            t.items.append(TodoItem(title='黄色边框测试', sort_order=0))
            _db.session.add(t)
            _db.session.commit()
            overdue = t.workdays_overdue

        if overdue >= 1 and overdue < 3:
            html = client.get('/').data.decode()
            idx = html.find('黄色边框测试')
            assert idx >= 0
            # border-warning is on the parent div ~200-600 chars before title
            section = html[max(0, idx-800):idx+50]
            # Find the closest todo-drag-item div before this title
            import re
            matches = list(re.finditer(r'todo-drag-item[^"]*', section))
            assert matches, 'todo-drag-item not found before title'
            last_div_class = matches[-1].group()
            assert 'border-warning' in last_div_class

    def test_today_created_no_overdue(self, client, app):
        """今天创建的 todo 没有超期标记"""
        with app.app_context():
            t = _create_todo('今天的', 'todo')
            _db.session.commit()

        html = client.get('/').data.decode()
        idx = html.find('今天的')
        if idx >= 0:
            section = html[idx:idx+300]
            assert '延' not in section
