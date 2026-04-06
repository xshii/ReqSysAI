"""
周报功能测试：子项目进展编辑、冻结、收件人
用法: python -m pytest tests/test_weekly_report.py -v
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
        from app.models.user import Role, User
        admin_role = Role(name='Admin')
        _db.session.add(admin_role)
        _db.session.flush()
        u1 = User(employee_id='t001', name='张三', ip_address='127.0.0.1',
                   group='TestGroup', manager='王总 m001')
        u1.roles.append(admin_role)
        u2 = User(employee_id='t002', name='李四', ip_address='127.0.0.2',
                   group='TestGroup')
        _db.session.add_all([u1, u2])
        _db.session.flush()
        # Parent project + child project
        from app.models.project import Project
        parent = Project(name='父项目', created_by=u1.id, status='active', owner_id=u1.id)
        _db.session.add(parent)
        _db.session.flush()
        child = Project(name='子项目A', created_by=u1.id, status='active',
                        parent_id=parent.id, owner_id=u2.id)
        _db.session.add(child)
        _db.session.flush()
        # Members
        from app.models.project_member import ProjectMember
        _db.session.add(ProjectMember(project_id=parent.id, user_id=u1.id, project_role='PM'))
        _db.session.add(ProjectMember(project_id=child.id, user_id=u2.id, project_role='DEV'))
        _db.session.commit()
        yield app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s['_user_id'] = '1'
        yield c


def _monday():
    today = date.today()
    return today - timedelta(days=today.weekday())


class TestSubSummarySave:
    """子项目进展 AJAX 编辑保存"""

    def test_save(self, client, app):
        with app.app_context():
            from app.models.project import Project
            child = Project.query.filter_by(name='子项目A').first()
            cid = child.id
        resp = client.post('/dashboard/weekly-report/sub-summary', json={
            'project_id': cid,
            'week_start': _monday().isoformat(),
            'summary': '本周完成接口联调'
        })
        d = resp.get_json()
        assert d['ok']
        # Verify persisted
        with app.app_context():
            from app.models.report import WeeklyReport
            wr = WeeklyReport.query.filter_by(project_id=cid, week_start=_monday()).first()
            assert wr is not None
            assert wr.summary == '本周完成接口联调'

    def test_update_existing(self, client, app):
        with app.app_context():
            from app.models.project import Project
            cid = Project.query.filter_by(name='子项目A').first().id
        # Save twice — should update, not duplicate
        client.post('/dashboard/weekly-report/sub-summary', json={
            'project_id': cid, 'week_start': _monday().isoformat(), 'summary': '第一版'
        })
        client.post('/dashboard/weekly-report/sub-summary', json={
            'project_id': cid, 'week_start': _monday().isoformat(), 'summary': '第二版'
        })
        with app.app_context():
            from app.models.report import WeeklyReport
            wrs = WeeklyReport.query.filter_by(project_id=cid, week_start=_monday()).all()
            assert len(wrs) == 1
            assert wrs[0].summary == '第二版'

    def test_frozen_reject(self, client, app):
        with app.app_context():
            from app.models.project import Project
            from app.models.report import WeeklyReport
            cid = Project.query.filter_by(name='子项目A').first().id
            wr = WeeklyReport.query.filter_by(project_id=cid, week_start=_monday()).first()
            if wr:
                wr.is_frozen = True
                _db.session.commit()
        resp = client.post('/dashboard/weekly-report/sub-summary', json={
            'project_id': cid, 'week_start': _monday().isoformat(), 'summary': '不该保存'
        })
        d = resp.get_json()
        assert not d['ok']
        assert '冻结' in d['msg']
        # Cleanup
        with app.app_context():
            from app.models.report import WeeklyReport
            wr = WeeklyReport.query.filter_by(project_id=cid, week_start=_monday()).first()
            if wr:
                wr.is_frozen = False
                _db.session.commit()

    def test_missing_params(self, client):
        resp = client.post('/dashboard/weekly-report/sub-summary', json={})
        d = resp.get_json()
        assert not d['ok']

    def test_truncate_long_summary(self, client, app):
        with app.app_context():
            from app.models.project import Project
            cid = Project.query.filter_by(name='子项目A').first().id
        long_text = 'x' * 300
        client.post('/dashboard/weekly-report/sub-summary', json={
            'project_id': cid, 'week_start': _monday().isoformat(), 'summary': long_text
        })
        with app.app_context():
            from app.models.report import WeeklyReport
            wr = WeeklyReport.query.filter_by(project_id=cid, week_start=_monday()).first()
            assert len(wr.summary) == 200


class TestRecipientsWithSubProjects:
    """收件人包含子项目成员（通过站会 EML API 间接测试）"""

    def _get_parent_id(self, app):
        with app.app_context():
            from app.models.project import Project
            return Project.query.filter_by(name='父项目').first().id

    def test_eml_to_includes_sub_members(self, client, app):
        """站会 EML 的 To 包含子项目成员"""
        pid = self._get_parent_id(app)
        resp = client.post('/api/standup-eml', json={'project_id': pid})
        d = resp.get_json()
        assert d['ok']
        # t001 (parent member) + t002 (child member)
        assert 't001' in d['to']
        assert 't002' in d['to']

    def test_eml_cc_has_manager(self, client, app):
        """站会 EML 的 Cc 包含直属主管"""
        pid = self._get_parent_id(app)
        # Enable project mode for standup_eml
        client.post('/profile/toggle-team-view')  # → project
        resp = client.post('/api/standup-eml', json={'project_id': pid})
        d = resp.get_json()
        assert d['ok']
        # m001 is 张三's manager
        assert 'm001' in d['cc']
        client.post('/profile/toggle-team-view')  # → group

    def test_eml_html_shows_recipients(self, client, app):
        """邮件 HTML body 里显示 To/Cc 姓名"""
        pid = self._get_parent_id(app)
        resp = client.post('/api/standup-eml', json={'project_id': pid})
        d = resp.get_json()
        assert 'To:' in d['html']
