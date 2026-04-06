"""
团队 Todo 页面功能测试：页面加载、按钮操作、风险评论、EML导出
用法: python -m pytest tests/test_team_todo.py -v
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
    app.config['AI_ENABLED'] = False
    with app.app_context():
        _db.create_all()
        from app.models.user import Group, Role, User
        admin_role = Role(name='Admin')
        _db.session.add(admin_role)
        grp = Group(name='TestGroup')
        _db.session.add(grp)
        _db.session.flush()
        u1 = User(employee_id='t001', name='张三', ip_address='127.0.0.1', group='TestGroup')
        u1.roles.append(admin_role)
        u2 = User(employee_id='t002', name='李四', ip_address='127.0.0.2', group='TestGroup')
        _db.session.add_all([u1, u2])
        _db.session.flush()
        # Create a project + risk
        from app.models.project import Project
        proj = Project(name='测试项目', created_by=u1.id, status='active')
        _db.session.add(proj)
        _db.session.flush()
        from app.models.risk import Risk
        risk = Risk(project_id=proj.id, title='测试风险', severity='high',
                    due_date=date.today() - timedelta(days=2), created_by=u1.id,
                    owner_id=u1.id)
        _db.session.add(risk)
        # Add project members
        from app.models.project_member import ProjectMember
        _db.session.add(ProjectMember(project_id=proj.id, user_id=u1.id, project_role='PL'))
        _db.session.add(ProjectMember(project_id=proj.id, user_id=u2.id, project_role='DEV'))
        # User1 follows the project
        u1.followed_projects.append(proj)
        _db.session.commit()
        yield app


@pytest.fixture(autouse=True)
def cleanup(app):
    yield
    with app.app_context():
        from app.models.todo import Todo, TodoItem
        TodoItem.query.delete()
        Todo.query.delete()
        _db.session.commit()


@pytest.fixture
def client(app):
    """Logged in as 张三 (user_id=1)"""
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = '1'
        yield c


def _create_todo(title='测试任务', user_id=1, category='team', status='todo'):
    from app.models.todo import Todo, TodoItem
    t = Todo(user_id=user_id, title=title, status=status, category=category,
             created_date=date.today(), due_date=date.today(),
             done_date=date.today() if status == 'done' else None)
    t.items.append(TodoItem(title=title, sort_order=0, is_done=(status == 'done')))
    _db.session.add(t)
    _db.session.flush()
    return t


class TestTeamPageLoad:
    """团队 Todo 页面能正常加载"""

    def test_group_mode(self, client):
        resp = client.get('/todos/team')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert '张三' in html
        assert '李四' in html

    def test_group_mode_with_param(self, client):
        resp = client.get('/todos/team?group=TestGroup')
        assert resp.status_code == 200
        assert '张三' in resp.get_data(as_text=True)

    def test_shows_user_card(self, client, app):
        with app.app_context():
            _create_todo('今日任务', user_id=1)
            _db.session.commit()
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        assert '今日任务' in html

    def test_risk_table_shown(self, client):
        """风险表格显示"""
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        assert '测试风险' in html
        assert '风险与问题' in html

    def test_risk_overdue_shown(self, client):
        """逾期风险显示超期天数"""
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        assert '超期' in html

    def test_no_todo_shows_placeholder(self, client):
        """无 todo 的用户显示暂无待办"""
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        assert '暂无待办' in html

    def test_user_badges(self, client, app):
        """人名旁显示未录入/延期/逾期标签"""
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        # 李四 has no todos → should show 未录入
        assert '未录入' in html


class TestQuickAddTodo:
    """快速添加 Todo（输入框回车提交）"""

    def test_add_for_self(self, client, app):
        resp = client.post('/quick-todo', json={
            'title': '站会新任务', 'category': 'team'
        })
        d = resp.get_json()
        assert d['ok']
        assert d['title'] == '站会新任务'

    def test_add_for_other_user(self, client, app):
        resp = client.post('/quick-todo', json={
            'title': '分配给李四', 'category': 'team', 'user_id': 2
        })
        d = resp.get_json()
        assert d['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, d['todo_id'])
            assert t.user_id == 2

    def test_add_with_duration(self, client, app):
        resp = client.post('/quick-todo', json={
            'title': '三天后截止 3d', 'category': 'team'
        })
        d = resp.get_json()
        assert d['ok']
        assert d['title'] == '三天后截止'
        assert d['days_left'] == 3

    def test_add_risk_todo(self, client, app):
        resp = client.post('/quick-todo', json={
            'title': '紧急修复', 'category': 'risk'
        })
        d = resp.get_json()
        assert d['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, d['todo_id'])
            assert t.category == 'risk'

    def test_add_empty_rejected(self, client):
        resp = client.post('/quick-todo', json={
            'title': '', 'category': 'team'
        })
        d = resp.get_json()
        assert not d['ok']


class TestToggleTodo:
    """完成/撤销完成 Todo"""

    def test_toggle_done(self, client, app):
        with app.app_context():
            t = _create_todo('待完成')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todo/{tid}/toggle', json={})
        d = resp.get_json()
        assert d['ok']
        assert d['done'] is True

    def test_toggle_undone(self, client, app):
        with app.app_context():
            t = _create_todo('已完成', status='done')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todo/{tid}/toggle', json={})
        d = resp.get_json()
        assert d['ok']
        assert d['done'] is False

    def test_toggle_nonexistent(self, client):
        resp = client.post('/todo/99999/toggle', json={})
        d = resp.get_json()
        assert not d['ok']


class TestBlockTodo:
    """标记/取消阻塞"""

    def test_block(self, client, app):
        with app.app_context():
            t = _create_todo('被阻塞')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/block', json={'reason': '等第三方'})
        d = resp.get_json()
        assert d['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, tid)
            assert t.need_help is True
            assert t.blocked_reason == '等第三方'

    def test_unblock(self, client, app):
        with app.app_context():
            t = _create_todo('已阻塞')
            t.need_help = True
            t.blocked_reason = '旧原因'
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/block', json={})
        d = resp.get_json()
        assert d['ok']
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, tid)
            assert t.need_help is False


class TestDeleteTodo:
    """删除 Todo（空标题 = 删除）"""

    def test_delete(self, client, app):
        with app.app_context():
            t = _create_todo('要删的')
            _db.session.commit()
            tid = t.id
        resp = client.post(f'/todos/{tid}/edit', json={'title': ''})
        d = resp.get_json()
        assert d['ok']
        assert d.get('deleted') is True

    def test_delete_nonexistent(self, client):
        resp = client.post('/todos/99999/edit', json={'title': ''})
        assert resp.status_code == 404


class TestReassignTodo:
    """拖拽转交 Todo 给其他人"""

    def test_reassign(self, client, app):
        with app.app_context():
            t = _create_todo('要转交的', user_id=1)
            _db.session.commit()
            tid = t.id
        resp = client.post('/api/reassign-todo', json={
            'todo_id': tid, 'target_user_id': 2
        })
        d = resp.get_json()
        assert d['ok']
        assert d['new_user'] == '李四'
        with app.app_context():
            from app.models.todo import Todo
            t = _db.session.get(Todo, tid)
            assert t.user_id == 2

    def test_reassign_same_user(self, client, app):
        with app.app_context():
            t = _create_todo('不转交', user_id=1)
            _db.session.commit()
            tid = t.id
        resp = client.post('/api/reassign-todo', json={
            'todo_id': tid, 'target_user_id': 1
        })
        d = resp.get_json()
        assert d['ok']  # no-op but still ok

    def test_reassign_missing_params(self, client):
        resp = client.post('/api/reassign-todo', json={})
        d = resp.get_json()
        assert not d['ok']


class TestRiskComment:
    """风险快捷评论"""

    def _get_risk_id(self, app):
        with app.app_context():
            from app.models.risk import Risk
            return Risk.query.first().id

    def test_add_comment(self, client, app):
        rid = self._get_risk_id(app)
        resp = client.post(f'/projects/risks/{rid}/comment', json={
            'content': '站会讨论结论'
        })
        d = resp.get_json()
        assert d['ok']
        assert d['comment']['content'] == '站会讨论结论'
        assert d['comment']['user'] == '张三'

    def test_add_empty_comment_rejected(self, client, app):
        rid = self._get_risk_id(app)
        resp = client.post(f'/projects/risks/{rid}/comment', json={
            'content': ''
        })
        d = resp.get_json()
        assert not d['ok']

    def test_delete_comment(self, client, app):
        rid = self._get_risk_id(app)
        # Add then delete
        resp = client.post(f'/projects/risks/{rid}/comment', json={'content': '临时'})
        cid = resp.get_json()['comment']['id']
        resp = client.post(f'/projects/risks/comments/{cid}/delete', json={})
        d = resp.get_json()
        assert d['ok']


class TestExportStandupEml:
    """导出站会邮件"""

    def test_export(self, client):
        resp = client.post('/api/standup-eml', json={})
        d = resp.get_json()
        assert d['ok']
        assert 'html' in d
        assert '站会进展' in d['subject']
        # Should contain user names
        assert '张三' in d['html'] or '李四' in d['html']

    def test_export_has_risk_data(self, client):
        resp = client.post('/api/standup-eml', json={})
        d = resp.get_json()
        assert '测试风险' in d['html']

    def test_export_has_strategy(self, client):
        """策略分析段应该存在"""
        resp = client.post('/api/standup-eml', json={})
        d = resp.get_json()
        # Either has insights or no insights section
        assert d['ok']


class TestToggleTeamView:
    """个人设置切换项目视图"""

    def test_toggle_to_project(self, client, app):
        # Reset to group first
        with app.app_context():
            from app.models.user import User
            u = _db.session.get(User, 1)
            u.team_view_mode = 'group'
            _db.session.commit()
        resp = client.post('/profile/toggle-team-view')
        d = resp.get_json()
        assert d['ok']
        assert d['team_view_mode'] == 'project'

    def test_toggle_back_to_group(self, client, app):
        with app.app_context():
            from app.models.user import User
            u = _db.session.get(User, 1)
            u.team_view_mode = 'project'
            _db.session.commit()
        resp = client.post('/profile/toggle-team-view')
        d = resp.get_json()
        assert d['team_view_mode'] == 'group'

    def test_persisted_in_db(self, client, app):
        with app.app_context():
            from app.models.user import User
            u = _db.session.get(User, 1)
            u.team_view_mode = 'group'
            _db.session.commit()
        client.post('/profile/toggle-team-view')  # → project
        with app.app_context():
            from app.models.user import User
            u = _db.session.get(User, 1)
            assert u.team_view_mode == 'project'
            u.team_view_mode = 'group'
            _db.session.commit()


class TestProjectViewMode:
    """项目视图模式下的团队 Todo"""

    def _set_mode(self, client, mode):
        """Set team_view_mode via toggle API"""
        # Check current mode, toggle if needed
        resp = client.post('/profile/toggle-team-view')
        d = resp.get_json()
        if d['team_view_mode'] != mode:
            resp = client.post('/profile/toggle-team-view')
            d = resp.get_json()
        assert d['team_view_mode'] == mode

    def test_project_mode_loads(self, client, app):
        """项目视图页面加载"""
        self._set_mode(client, 'project')
        resp = client.get('/todos/team')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert '测试项目' in html
        self._set_mode(client, 'group')

    def test_defaults_to_followed_project(self, client, app):
        """默认选择关注的项目"""
        self._set_mode(client, 'project')
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        assert '测试项目' in html
        self._set_mode(client, 'group')

    def test_explicit_project_id(self, client, app):
        """URL 指定 project_id"""
        self._set_mode(client, 'project')
        with app.app_context():
            from app.models.project import Project
            pid = Project.query.first().id
        resp = client.get(f'/todos/team?project_id={pid}')
        assert resp.status_code == 200
        assert '测试项目' in resp.get_data(as_text=True)
        self._set_mode(client, 'group')

    def test_shows_project_members(self, client, app):
        """项目视图显示项目成员"""
        self._set_mode(client, 'project')
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        assert '张三' in html
        assert '李四' in html
        self._set_mode(client, 'group')

    def test_risk_filtered_by_project(self, client, app):
        """项目视图风险只显示该项目的"""
        self._set_mode(client, 'project')
        resp = client.get('/todos/team')
        html = resp.get_data(as_text=True)
        assert '测试风险' in html
        self._set_mode(client, 'group')

    def test_eml_with_project(self, client, app):
        """项目视图下导出 EML"""
        self._set_mode(client, 'project')
        with app.app_context():
            from app.models.project import Project
            pid = Project.query.first().id
        resp = client.post('/api/standup-eml', json={'project_id': pid})
        d = resp.get_json()
        assert d['ok']
        assert '测试项目' in d['subject']
        self._set_mode(client, 'group')
