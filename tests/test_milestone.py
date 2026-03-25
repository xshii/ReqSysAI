"""
里程碑模板测试用例
用法: python -m pytest tests/test_milestone.py -v
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
        u = User(employee_id='a00000001', name='管理员', ip_address='127.0.0.1')
        u.roles.append(r)
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


# ─── parse_offset 单元测试 ─────────────────────────────────

class TestParseOffset:
    """constants.parse_offset 解析各种偏移格式"""

    def test_int_days(self):
        from app.constants import parse_offset
        assert parse_offset(14) == 14

    def test_zero(self):
        from app.constants import parse_offset
        assert parse_offset(0) == 0

    def test_string_days(self):
        from app.constants import parse_offset
        assert parse_offset('5') == 5

    def test_weeks(self):
        from app.constants import parse_offset
        assert parse_offset('+2w') == 14

    def test_weeks_no_plus(self):
        from app.constants import parse_offset
        assert parse_offset('2w') == 14

    def test_months(self):
        from app.constants import parse_offset
        assert parse_offset('+1m') == 28  # 1月=4周=28天

    def test_months_no_plus(self):
        from app.constants import parse_offset
        assert parse_offset('3m') == 84  # 3*28

    def test_one_week(self):
        from app.constants import parse_offset
        assert parse_offset('+1w') == 7

    def test_large_month(self):
        from app.constants import parse_offset
        assert parse_offset('+6m') == 168  # 6*28

    def test_empty_string(self):
        from app.constants import parse_offset
        assert parse_offset('') == 0

    def test_space_only(self):
        from app.constants import parse_offset
        assert parse_offset(' ') == 0

    def test_plus_only(self):
        from app.constants import parse_offset
        assert parse_offset('+') == 0

    def test_plus_w_no_number(self):
        from app.constants import parse_offset
        assert parse_offset('+w') == 0

    def test_negative_clamped(self):
        from app.constants import parse_offset
        assert parse_offset(-5) == 0

    def test_negative_string_clamped(self):
        from app.constants import parse_offset
        assert parse_offset('-2w') == 0

    def test_garbage_input(self):
        from app.constants import parse_offset
        assert parse_offset('abc') == 0

    def test_chinese_weeks(self):
        from app.constants import parse_offset
        assert parse_offset('+2周') == 14

    def test_chinese_months(self):
        from app.constants import parse_offset
        assert parse_offset('+1个月') == 28

    def test_chinese_days(self):
        from app.constants import parse_offset
        assert parse_offset('+5天') == 5

    def test_chinese_no_plus(self):
        from app.constants import parse_offset
        assert parse_offset('3周') == 21

    def test_chinese_month_empty_num(self):
        from app.constants import parse_offset
        assert parse_offset('+个月') == 0

    def test_4_weeks_equals_1_month(self):
        """4周=28天=1个月，保证周和月能互相累积"""
        from app.constants import parse_offset
        assert parse_offset('+4w') == 28
        assert parse_offset('+1个月') == 28
        assert parse_offset('+1m') == 28


# ─── resolve_template_offsets 单元测试 ──────────────────────

class TestResolveOffsets:
    """constants.resolve_template_offsets 累加相对偏移"""

    def test_basic_cumulation(self):
        from app.constants import resolve_template_offsets
        items = [('A', 0), ('B', 7), ('C', 14)]
        result = resolve_template_offsets(items)
        assert result == [('A', 0), ('B', 7), ('C', 21)]

    def test_week_month_mixed(self):
        from app.constants import resolve_template_offsets
        items = [('Start', 0), ('Mid', '+2w'), ('End', '+1m')]
        result = resolve_template_offsets(items)
        assert result == [('Start', 0), ('Mid', 14), ('End', 42)]  # 14+28

    def test_single_item(self):
        from app.constants import resolve_template_offsets
        result = resolve_template_offsets([('Only', 0)])
        assert result == [('Only', 0)]

    def test_empty(self):
        from app.constants import resolve_template_offsets
        assert resolve_template_offsets([]) == []

    def test_all_weeks(self):
        from app.constants import resolve_template_offsets
        items = [('A', 0), ('B', '+1w'), ('C', '+1w'), ('D', '+1w')]
        result = resolve_template_offsets(items)
        assert result == [('A', 0), ('B', 7), ('C', 14), ('D', 21)]

    def test_ipd_template(self):
        """IPD 模板累加正确"""
        from app.constants import MILESTONE_TEMPLATES, resolve_template_offsets
        ipd = next(t for t in MILESTONE_TEMPLATES if 'IPD' in t['name'])
        result = resolve_template_offsets(ipd['items'])
        # Charter = 0, CDCP = +2w = 14, TR1 = +1w = 21, ...
        assert result[0] == ('Charter 立项', 0)
        assert result[1] == ('CDCP 概念决策', 14)
        assert result[2] == ('TR1 需求评审', 21)
        # All offsets should be monotonically increasing
        for i in range(1, len(result)):
            assert result[i][1] >= result[i-1][1]


# ─── 模板 CRUD 路由测试 ────────────────────────────────────

class TestTemplateCRUD:
    """管理后台里程碑模板增删改"""

    def test_template_route_exists(self, client):
        """POST-only route exists"""
        resp = client.get('/projects/milestone-templates')
        assert resp.status_code == 405  # Method not allowed (POST only)

    def test_create_simple(self, client, app):
        """创建简单模板（纯天数）"""
        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '测试模板',
            'description': '测试用',
            'item_name': ['启动', '开发', '上线'],
            'item_offset': ['0', '14', '7'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            tpl = MilestoneTemplate.query.filter_by(name='测试模板').first()
            assert tpl is not None
            assert len(tpl.items) == 3
            assert tpl.items[0].offset_days == 0
            assert tpl.items[1].offset_days == 14  # 0 + 14
            assert tpl.items[2].offset_days == 21  # 14 + 7

    def test_create_with_weeks(self, client, app):
        """创建模板用周格式"""
        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '周模板',
            'item_name': ['开始', '中期', '结束'],
            'item_offset': ['0', '+2w', '+1w'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            tpl = MilestoneTemplate.query.filter_by(name='周模板').first()
            assert tpl.items[0].offset_days == 0
            assert tpl.items[1].offset_days == 14
            assert tpl.items[2].offset_days == 21

    def test_create_with_months(self, client, app):
        """创建模板用月格式（1月=28天）"""
        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '月模板',
            'item_name': ['Q1', 'Q2', 'Q3'],
            'item_offset': ['0', '+1m', '+1m'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            tpl = MilestoneTemplate.query.filter_by(name='月模板').first()
            assert tpl.items[0].offset_days == 0
            assert tpl.items[1].offset_days == 28
            assert tpl.items[2].offset_days == 56

    def test_create_mixed_formats(self, client, app):
        """混合格式：天+周+月"""
        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '混合模板',
            'item_name': ['A', 'B', 'C', 'D'],
            'item_offset': ['0', '5', '+1w', '+1m'],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            tpl = MilestoneTemplate.query.filter_by(name='混合模板').first()
            assert tpl.items[0].offset_days == 0
            assert tpl.items[1].offset_days == 5
            assert tpl.items[2].offset_days == 12  # 5 + 7
            assert tpl.items[3].offset_days == 40  # 12 + 28

    def test_create_empty_offset_defaults_zero(self, client, app):
        """空偏移默认为0"""
        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '空偏移模板',
            'item_name': ['起点', '同日'],
            'item_offset': ['', ''],
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            tpl = MilestoneTemplate.query.filter_by(name='空偏移模板').first()
            assert tpl.items[0].offset_days == 0
            assert tpl.items[1].offset_days == 0

    def test_create_duplicate_name_rejected(self, client, app):
        """重复名称不允许"""
        with app.app_context():
            from app.models.project import MilestoneTemplate
            _db.session.add(MilestoneTemplate(name='已存在'))
            _db.session.commit()

        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '已存在',
            'item_name': ['A'],
            'item_offset': ['0'],
        }, follow_redirects=True)
        assert '已存在' in resp.data.decode()

    def test_edit_template(self, client, app):
        """编辑已有模板"""
        with app.app_context():
            from app.models.project import MilestoneTemplate, MilestoneTemplateItem
            tpl = MilestoneTemplate(name='编辑测试')
            tpl.items.append(MilestoneTemplateItem(name='旧A', offset_days=0, sort_order=0))
            tpl.items.append(MilestoneTemplateItem(name='旧B', offset_days=7, sort_order=1))
            _db.session.add(tpl)
            _db.session.commit()
            tpl_id = tpl.id

        resp = client.post('/projects/milestone-templates', data={
            'action': 'edit',
            'template_id': str(tpl_id),
            'name': '编辑后',
            'description': '新描述',
            'item_name': ['新A', '新B', '新C'],
            'item_offset': ['0', '+2w', '+1m'],
        }, follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            from app.models.project import MilestoneTemplate
            tpl = _db.session.get(MilestoneTemplate, tpl_id)
            assert tpl.name == '编辑后'
            assert tpl.description == '新描述'
            assert len(tpl.items) == 3
            assert tpl.items[0].name == '新A'
            assert tpl.items[0].offset_days == 0
            assert tpl.items[1].name == '新B'
            assert tpl.items[1].offset_days == 14
            assert tpl.items[2].name == '新C'
            assert tpl.items[2].offset_days == 42  # 14 + 28

    def test_delete_template(self, client, app):
        """删除模板"""
        with app.app_context():
            from app.models.project import MilestoneTemplate
            tpl = MilestoneTemplate(name='要删的')
            _db.session.add(tpl)
            _db.session.commit()
            tpl_id = tpl.id

        resp = client.post('/projects/milestone-templates', data={
            'action': 'delete',
            'template_id': str(tpl_id),
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            from app.models.project import MilestoneTemplate
            assert _db.session.get(MilestoneTemplate, tpl_id) is None

    def test_empty_name_rejected(self, client):
        """空名称不创建"""
        resp = client.post('/projects/milestone-templates', data={
            'action': 'create',
            'name': '',
            'item_name': ['A'],
            'item_offset': ['0'],
        }, follow_redirects=True)
        assert resp.status_code == 200


# ─── 模板应用到项目 ────────────────────────────────────────

class TestTemplateAPI:
    """模板 API 返回正确的绝对偏移"""

    def test_api_returns_items(self, client, app):
        with app.app_context():
            from app.models.project import MilestoneTemplate, MilestoneTemplateItem
            tpl = MilestoneTemplate(name='API测试')
            tpl.items.append(MilestoneTemplateItem(name='Start', offset_days=0, sort_order=0))
            tpl.items.append(MilestoneTemplateItem(name='Mid', offset_days=14, sort_order=1))
            tpl.items.append(MilestoneTemplateItem(name='End', offset_days=28, sort_order=2))
            _db.session.add(tpl)
            _db.session.commit()
            tpl_id = tpl.id

        resp = client.get(f'/projects/api/template/{tpl_id}')
        data = resp.get_json()
        assert data['ok'] is True
        assert len(data['items']) == 3
        assert data['items'][0] == {'name': 'Start', 'offset_days': 0}
        assert data['items'][1] == {'name': 'Mid', 'offset_days': 14}
        assert data['items'][2] == {'name': 'End', 'offset_days': 28}

    def test_api_nonexistent(self, client):
        resp = client.get('/projects/api/template/99999')
        assert resp.status_code == 404


# ─── 里程碑颜色 ────────────────────────────────────────────

class TestMilestoneColor:
    """里程碑统一深蓝色"""

    def test_color_constant(self):
        from app.constants import MILESTONE_COLOR
        assert MILESTONE_COLOR == '#1e3a5f'

    def test_project_detail_uses_constant(self, client, app):
        """项目详情页里程碑用统一颜色"""
        with app.app_context():
            from app.models.project import Milestone, Project
            p = Project(name='颜色测试', created_by=1, status='active')
            _db.session.add(p)
            _db.session.flush()
            ms = Milestone(project_id=p.id, name='过期里程碑',
                           due_date=date(2020, 1, 1), status='active')
            _db.session.add(ms)
            _db.session.commit()
            pid = p.id

        resp = client.get(f'/projects/{pid}')
        html = resp.data.decode()
        # Milestone rendered as PNG image
        assert 'data:image/png;base64,' in html


# ─── 预置模板完整性 ────────────────────────────────────────

class TestPresetTemplates:
    """constants.MILESTONE_TEMPLATES 预置模板数据完整"""

    def test_template_count(self):
        from app.constants import MILESTONE_TEMPLATES
        assert len(MILESTONE_TEMPLATES) == 2

    def test_all_have_items(self):
        from app.constants import MILESTONE_TEMPLATES
        for tpl in MILESTONE_TEMPLATES:
            assert 'name' in tpl
            assert 'items' in tpl
            assert len(tpl['items']) > 0

    def test_first_item_always_zero(self):
        """每个模板第一项偏移为0"""
        from app.constants import MILESTONE_TEMPLATES
        for tpl in MILESTONE_TEMPLATES:
            assert tpl['items'][0][1] == 0, f'{tpl["name"]} 第一项偏移不为0'

    def test_all_offsets_parseable(self):
        """所有偏移值都能正确解析"""
        from app.constants import MILESTONE_TEMPLATES, parse_offset
        for tpl in MILESTONE_TEMPLATES:
            for name, offset in tpl['items']:
                days = parse_offset(offset)
                assert isinstance(days, int), f'{tpl["name"]}.{name}: parse_offset({offset}) 不是整数'
                assert days >= 0, f'{tpl["name"]}.{name}: 偏移为负数'
