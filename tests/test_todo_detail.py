"""
Todo 详情页测试用例 (todo/)
用法: python -m pytest tests/test_todo_detail.py -v
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
        r = Role(name='Admin')
        _db.session.add(r)
        _db.session.flush()
        from app.models.user import Group
        _db.session.add(Group(name='TestGrp'))
        u = User(employee_id='t001', name='测试用户', ip_address='127.0.0.1', group='TestGrp')
        u.roles.append(r)
        _db.session.add(u)
        u2 = User(employee_id='t002', name='帮助者', ip_address='127.0.0.2', group='TestGrp')
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


def _make_todo(title='测试', user_id=1):
    from app.models.todo import Todo, TodoItem
    t = Todo(user_id=user_id, title=title, created_date=date.today(), status='todo')
    t.items.append(TodoItem(title=title, sort_order=0))
    _db.session.add(t)
    _db.session.flush()
    return t


# ─── 编辑 ───────────────────────────────────────────────────

class TestTodoEdit:
    """Todo 编辑（标题、截止日期、删除）"""

    def test_edit_title(self, client, app):
        with app.app_context():
            t = _make_todo('旧标题')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/edit', json={'title': '新标题'})
        assert resp.get_json()['ok'] is True
        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid).title == '新标题'

    def test_edit_due_date(self, client, app):
        with app.app_context():
            t = _make_todo('截止日期')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/edit', json={'title': '截止日期', 'due_date': '2026-04-01'})
        assert resp.get_json()['ok'] is True
        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid).due_date == date(2026, 4, 1)

    def test_edit_empty_title_deletes(self, client, app):
        with app.app_context():
            t = _make_todo('要删')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/edit', json={'title': ''})
        assert resp.get_json()['ok'] is True
        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid) is None

    def test_edit_other_user_allowed(self, client, app):
        """团队协作：可编辑别人的todo"""
        with app.app_context():
            t = _make_todo('他人', user_id=2)
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/edit', json={'title': '可以改'})
        assert resp.get_json()['ok'] is True


# ─── 番茄钟 ─────────────────────────────────────────────────

class TestTimer:
    """番茄钟启停"""

    def test_start_timer(self, client, app):
        with app.app_context():
            t = _make_todo('计时')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/timer', json={})
        data = resp.get_json()
        assert data['ok'] is True
        assert data['running'] is True

    def test_stop_timer(self, client, app):
        with app.app_context():
            from datetime import datetime, timedelta
            t = _make_todo('停止计时')
            t.started_at = datetime.now() - timedelta(minutes=10)
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/timer', json={})
        data = resp.get_json()
        assert data['ok'] is True
        assert data['running'] is False
        assert data.get('minutes', 0) >= 9  # ~10 min


# ─── 阻塞 ───────────────────────────────────────────────────

class TestBlock:
    """Todo 阻塞/解阻塞"""

    def test_block_with_reason(self, client, app):
        with app.app_context():
            t = _make_todo('阻塞测试')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/block', json={'reason': '等待审批'})
        data = resp.get_json()
        assert data['ok'] is True
        with app.app_context():
            from app.models.todo import Todo
            todo = _db.session.get(Todo, tid)
            assert todo.need_help is True
            assert todo.blocked_reason == '等待审批'

    def test_unblock(self, client, app):
        with app.app_context():
            t = _make_todo('解阻塞')
            t.need_help = True
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/block', json={})
        assert resp.get_json()['ok'] is True
        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid).need_help is False


# ─── 子项 ───────────────────────────────────────────────────

class TestSubItems:
    """Todo 子项（checklist）"""

    def test_add_item(self, client, app):
        with app.app_context():
            t = _make_todo('子项测试')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/items/add', json={'title': '子任务A'})
        assert resp.get_json()['ok'] is True

    def test_toggle_item(self, client, app):
        with app.app_context():
            t = _make_todo('toggle子项')
            _db.session.commit()
            item_id = t.items[0].id
        resp = client.post(f'/todos/items/{item_id}/toggle', json={})
        data = resp.get_json()
        assert data['ok'] is True
        assert data['is_done'] is True

    def test_delete_item(self, client, app):
        with app.app_context():
            from app.models.todo import TodoItem
            t = _make_todo('删子项')
            extra = TodoItem(title='多余子项', sort_order=1)
            t.items.append(extra)
            _db.session.commit()
            item_id = extra.id
        resp = client.post(f'/todos/items/{item_id}/delete', json={})
        assert resp.get_json()['ok'] is True


# ─── 任务转交 ───────────────────────────────────────────────

class TestReassign:
    """跨成员任务转交"""

    def test_reassign_to_other_user(self, client, app):
        """转交 todo 到另一个用户"""
        with app.app_context():
            t = _make_todo('转交测试', user_id=1)
            _db.session.commit()
            tid = t.id

        resp = client.post('/api/reassign-todo', json={
            'todo_id': tid, 'target_user_id': 2,
        })
        data = resp.get_json()
        assert data['ok'] is True
        assert data['new_user'] == '帮助者'
        assert data['old_user'] == '测试用户'

        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid).user_id == 2

    def test_reassign_preserves_content(self, client, app):
        """转交后标题、状态、需求关联不变"""
        with app.app_context():
            t = _make_todo('保持内容', user_id=1)
            t.need_help = True
            t.blocked_reason = '等审批'
            _db.session.commit()
            tid = t.id

        client.post('/api/reassign-todo', json={
            'todo_id': tid, 'target_user_id': 2,
        })

        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, tid)
            assert t.user_id == 2
            assert t.title == '保持内容'
            assert t.need_help is True
            assert t.blocked_reason == '等审批'

    def test_reassign_nonexistent_todo(self, client):
        """转交不存在的 todo"""
        resp = client.post('/api/reassign-todo', json={
            'todo_id': 99999, 'target_user_id': 2,
        })
        assert resp.get_json()['ok'] is False

    def test_reassign_nonexistent_user(self, client, app):
        """转交到不存在的用户"""
        with app.app_context():
            t = _make_todo('转交给谁', user_id=1)
            _db.session.commit()
            tid = t.id

        resp = client.post('/api/reassign-todo', json={
            'todo_id': tid, 'target_user_id': 99999,
        })
        assert resp.get_json()['ok'] is False

    def test_reassign_missing_params(self, client):
        """缺少参数"""
        resp = client.post('/api/reassign-todo', json={})
        assert resp.get_json()['ok'] is False

    def test_team_page_shows_draggable(self, client, app):
        """团队页面 todo 行有 draggable 属性"""
        with app.app_context():
            _make_todo('可拖拽', user_id=1)
            _db.session.commit()

        resp = client.get('/todos/team')
        html = resp.data.decode()
        assert 'draggable="true"' in html
        assert 'team-user-card' in html

    def test_team_page_shows_group_users(self, client, app):
        """团队页面显示同组用户"""
        with app.app_context():
            _make_todo('用户1任务', user_id=1)
            _make_todo('用户2任务', user_id=2)
            _db.session.commit()

        resp = client.get('/todos/team')
        html = resp.data.decode()
        assert '测试用户' in html
        assert '帮助者' in html

    def test_reassign_to_self_noop(self, client, app):
        """转交给自己不报错"""
        with app.app_context():
            t = _make_todo('自转交', user_id=1)
            _db.session.commit()
            tid = t.id

        resp = client.post('/api/reassign-todo', json={
            'todo_id': tid, 'target_user_id': 1,
        })
        assert resp.get_json()['ok'] is True

        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, tid).user_id == 1

    def test_reassign_with_children(self, client, app):
        """转交带子 todo（帮助请求）的任务，子 todo 一起转"""
        with app.app_context():
            from app.models.todo import Todo, TodoItem
            parent = _make_todo('父任务', user_id=1)
            _db.session.flush()
            child = Todo(user_id=1, title='子任务', parent_id=parent.id,
                         created_date=date.today(), status='todo')
            child.items.append(TodoItem(title='子任务', sort_order=0))
            _db.session.add(child)
            _db.session.commit()
            pid = parent.id
            cid = child.id

        resp = client.post('/api/reassign-todo', json={
            'todo_id': pid, 'target_user_id': 2,
        })
        assert resp.get_json()['ok'] is True

        with app.app_context():
            from app.models.todo import Todo
            assert _db.session.get(Todo, pid).user_id == 2
            assert _db.session.get(Todo, cid).user_id == 2  # child follows parent
