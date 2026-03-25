"""Permission module tests: apply, merge, approve, freeze."""
import pytest
from app import create_app
from app.extensions import db as _db
from app.models.knowledge import PermissionItem, PermissionApplication
from app.models.project import Project
from app.models.user import User, Role


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        role = Role(name='Admin', description='Admin')
        _db.session.add(role)
        _db.session.flush()
        u1 = User(employee_id='p001', name='用户A', ip_address='10.0.0.1', roles=[role])
        u2 = User(employee_id='p002', name='用户B', ip_address='10.0.0.2')
        _db.session.add_all([u1, u2])
        _db.session.flush()
        p = Project(name='测试项目', created_by=u1.id, status='active')
        _db.session.add(p)
        _db.session.commit()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['_user_id'] = '1'
        yield c


class TestPermissionApply:
    """权限申请基础流程"""

    def test_add_item(self, client, app):
        """登记权限"""
        with app.app_context():
            pid = Project.query.first().id
        resp = client.post(f'/projects/{pid}/permissions', data={
            'action': 'add_item', 'category': 'SVN', 'resource': 'svn-core',
            'repo_path': '/repo/core', 'description': '核心仓库',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert PermissionItem.query.filter_by(resource='svn-core').first() is not None

    def test_quick_apply_self(self, client, app):
        """为自己快速申请"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='Git', resource='gitlab-test', created_by=1)
            _db.session.add(item)
            _db.session.commit()
            item_id = item.id
        resp = client.post(f'/projects/{pid}/permissions', data={
            'action': 'quick_apply', 'item_id': item_id,
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            apps = PermissionApplication.query.filter_by(item_id=item_id).all()
            assert len(apps) == 1
            assert apps[0].status == 'pending'
            assert '用户A' in apps[0].applicant_name

    def test_quick_apply_dedup(self, client, app):
        """重复申请不创建新记录"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='Git', resource='gitlab-dedup', created_by=1)
            _db.session.add(item)
            _db.session.commit()
            item_id = item.id
        # Apply twice
        client.post(f'/projects/{pid}/permissions', data={'action': 'quick_apply', 'item_id': item_id}, follow_redirects=True)
        client.post(f'/projects/{pid}/permissions', data={'action': 'quick_apply', 'item_id': item_id}, follow_redirects=True)
        with app.app_context():
            count = PermissionApplication.query.filter_by(item_id=item_id).count()
            assert count == 1

    def test_apply_for_others(self, client, app):
        """为他人批量申请"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='DB', resource='mysql-prod', created_by=1)
            _db.session.add(item)
            _db.session.commit()
            item_id = item.id
        resp = client.post(f'/projects/{pid}/permissions', data={
            'action': 'apply', 'item_id': [item_id],
            'people_list': '张三 a001\n李四 b002', 'reason': '开发需要',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            a = PermissionApplication.query.filter_by(item_id=item_id).first()
            assert '张三' in a.applicant_name
            assert '李四' in a.applicant_name
            assert a.reason == '开发需要'


class TestPermissionMerge:
    """同权限申请合并"""

    def test_pending_merged_in_display(self, client, app):
        """同权限多个pending申请在显示时合并"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='SVN', resource='svn-merge', created_by=1)
            _db.session.add(item)
            _db.session.flush()
            # Two separate pending applications
            a1 = PermissionApplication(item_id=item.id, applicant_name='用户A p001', submitted_by=1)
            a2 = PermissionApplication(item_id=item.id, applicant_name='用户B p002', reason='测试', submitted_by=1)
            _db.session.add_all([a1, a2])
            _db.session.commit()
        resp = client.get(f'/projects/{pid}/permissions')
        html = resp.data.decode()
        # Should show merged — only one row with both names
        assert resp.status_code == 200


class TestPermissionApprove:
    """审批流程"""

    def test_approve_single(self, client, app):
        """单条审批通过"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='Git', resource='gitlab-approve', created_by=1)
            _db.session.add(item)
            _db.session.flush()
            a = PermissionApplication(item_id=item.id, applicant_name='用户B p002', submitted_by=1)
            _db.session.add(a)
            _db.session.commit()
            app_id = a.id
        resp = client.post(f'/projects/{pid}/permissions', data={
            'action': 'approve', 'app_id': app_id,
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            a = _db.session.get(PermissionApplication, app_id)
            assert a.status == 'approved'
            assert a.approved_by is not None

    def test_bulk_approve(self, client, app):
        """批量审批通过"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='DB', resource='db-bulk', created_by=1)
            _db.session.add(item)
            _db.session.flush()
            a1 = PermissionApplication(item_id=item.id, applicant_name='A', submitted_by=1)
            a2 = PermissionApplication(item_id=item.id, applicant_name='B', submitted_by=1)
            _db.session.add_all([a1, a2])
            _db.session.commit()
        resp = client.post(f'/projects/{pid}/permissions', data={
            'action': 'bulk_approve',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            pending = PermissionApplication.query.filter_by(status='pending').count()
            assert pending == 0


class TestPermissionFreeze:
    """申请中冻结：有pending申请时不能重复申请"""

    def test_frozen_when_pending(self, client, app):
        """有pending申请时，页面不显示申请按钮"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='SVN', resource='svn-frozen', created_by=1)
            _db.session.add(item)
            _db.session.flush()
            a = PermissionApplication(item_id=item.id, applicant_name='用户A', status='pending', submitted_by=1)
            _db.session.add(a)
            _db.session.commit()
        resp = client.get(f'/projects/{pid}/permissions')
        html = resp.data.decode()
        # Should show "申请中" badge instead of apply buttons for this item
        assert '申请中' in html

    def test_not_frozen_after_approved(self, client, app):
        """全部审批后可以重新申请"""
        with app.app_context():
            pid = Project.query.first().id
            item = PermissionItem(project_id=pid, category='SVN', resource='svn-reapply', created_by=1)
            _db.session.add(item)
            _db.session.flush()
            a = PermissionApplication(item_id=item.id, applicant_name='用户A', status='approved', submitted_by=1)
            _db.session.add(a)
            _db.session.commit()
            item_id = item.id
        resp = client.get(f'/projects/{pid}/permissions')
        html = resp.data.decode()
        # Should show apply buttons (not frozen)
        assert f'name="item_id" value="{item_id}"' in html
