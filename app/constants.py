"""Centralized constants – eliminate magic strings & numbers across the codebase."""

# ---------------------------------------------------------------------------
# Site defaults
# ---------------------------------------------------------------------------
DEFAULT_SITE_NAME = '研发协作平台'

# ---------------------------------------------------------------------------
# Todo statuses
# ---------------------------------------------------------------------------
TODO_STATUS_TODO = 'todo'
TODO_STATUS_DONE = 'done'

# Todo categories (work counts for project investment, others don't)
TODO_CAT_WORK = 'work'
TODO_CAT_TEAM = 'team'
TODO_CAT_PERSONAL = 'personal'
TODO_CAT_RISK = 'risk'
TODO_CATEGORIES_FOR_INVESTMENT = (TODO_CAT_WORK,)  # Only work counts for project stats

# ---------------------------------------------------------------------------
# Requirement active-status filter (exclude these from "active" queries)
# Usage: Requirement.status.notin_(REQ_INACTIVE_STATUSES)
# ---------------------------------------------------------------------------
REQ_INACTIVE_STATUSES = ('done', 'closed')

# ---------------------------------------------------------------------------
# Contribution heatmap
# ---------------------------------------------------------------------------
HEATMAP_DAYS = 90

# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------
AI_TOKEN_RATIO = 0.6

# ---------------------------------------------------------------------------
# Quick-todo on homepage
# ---------------------------------------------------------------------------
MAX_RECENT_REQS_FOR_QUICK_TODO = 3

# ---------------------------------------------------------------------------
# Input length limits
# ---------------------------------------------------------------------------
MAX_COMMENT_LENGTH = 150
MAX_RANT_LENGTH = 500

# ---------------------------------------------------------------------------
# File uploads
# ---------------------------------------------------------------------------
ALLOWED_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')

# ---------------------------------------------------------------------------
# Help / due-date options
# ---------------------------------------------------------------------------
HELP_DUE_OPTIONS_COUNT = 3

# ---------------------------------------------------------------------------
# Pomodoro timer
# ---------------------------------------------------------------------------
DEFAULT_POMODORO_MINUTES = 45

# ---------------------------------------------------------------------------
# Incentive source (激励来源)
# ---------------------------------------------------------------------------
_INCENTIVE_SOURCE_DEFAULTS = {
    'instant': '及时激励',
    'special': '专项激励',
    'project': '项目激励',
    'knowledge': '知识管理激励',
    'improvement': '持续改进激励',
}

def _get_incentive_source_labels():
    import json
    import os
    result = dict(_INCENTIVE_SOURCE_DEFAULTS)
    path = os.path.join(os.path.dirname(__file__), 'custom_sources.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            result.update(json.load(f))
    return result


class _SourceLabelsProxy(dict):
    """Dict that reloads custom sources on every access."""
    def __getitem__(self, key):
        return _get_incentive_source_labels()[key]
    def get(self, key, default=None):
        return _get_incentive_source_labels().get(key, default)
    def items(self):
        return _get_incentive_source_labels().items()
    def keys(self):
        return _get_incentive_source_labels().keys()
    def values(self):
        return _get_incentive_source_labels().values()
    def __iter__(self):
        return iter(_get_incentive_source_labels())
    def __len__(self):
        return len(_get_incentive_source_labels())
    def __contains__(self, key):
        return key in _get_incentive_source_labels()

INCENTIVE_SOURCE_LABELS = _SourceLabelsProxy()

# ---------------------------------------------------------------------------
# Query & pagination limits
# ---------------------------------------------------------------------------
QUERY_LIMIT_MY_REQS = 10
QUERY_LIMIT_AI_RANKING = 5
QUERY_LIMIT_TOP_RANTS = 3
QUERY_LIMIT_RANTS_MONTH = 20
PAGINATION_PER_PAGE = 20
MAX_ALIAS_LENGTH = 30
AI_INPUT_MAX = 5000

# ---------------------------------------------------------------------------
# Time lookback periods (days)
# ---------------------------------------------------------------------------
LOOKBACK_WEEK = 7
LOOKBACK_MONTH = 30
LOOKBACK_QUARTER = 90
LOOKBACK_HALF_YEAR = 180
LOOKBACK_YEAR = 365

INCENTIVE_PERIOD_DAYS = {'1m': 30, '3m': 90, '6m': 180, '1y': 365}

# ---------------------------------------------------------------------------
# Weekday names (Chinese)
# ---------------------------------------------------------------------------
WEEKDAY_NAMES_ZH = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# ---------------------------------------------------------------------------
# Milestone colors
# ---------------------------------------------------------------------------
MILESTONE_COLOR = '#1e3a5f'

# ---------------------------------------------------------------------------
# Milestone templates (used by init_db.py)
# ---------------------------------------------------------------------------
MILESTONE_TEMPLATES = [
    {
        'name': 'IPD标准流程',
        'description': '华为IPD集成产品开发标准里程碑',
        # offset: relative to previous milestone, supports: days(int), '+Nw'(weeks), '+Nm'(months)
        'items': [
            ('Charter 立项', 0),
            ('CDCP 概念决策', '+2w'),
            ('TR1 需求评审', '+1w'),
            ('PDCP 计划决策', '+1w'),
            ('TR2 方案评审', '+2w'),
            ('TR3 详设评审', '+2w'),
            ('TR4 编码完成', '+1m'),
            ('TR5 系统测试', '+2w'),
            ('ADCP 发布决策', '+1w'),
            ('TR6 发布就绪', '+1w'),
            ('GA 正式发布', 5),
        ],
    },
    {
        'name': '简单项目（3阶段）',
        'description': '小型项目快速交付',
        'items': [
            ('需求确认', 0),
            ('开发完成', '+2w'),
            ('测试上线', '+1w'),
        ],
    },
]


def parse_offset(offset_str):
    """Parse offset: int, '+Nw'/'+N周', '+Nm'/'+N个月', '+N天' → days.
    Returns 0 for empty/invalid input. Negative values return 0."""
    if isinstance(offset_str, int):
        return max(0, offset_str)
    raw = str(offset_str).strip()
    if raw.startswith('-'):
        return 0
    s = raw.lstrip('+')
    if not s:
        return 0
    try:
        # Chinese formats (1月=4周=28天)
        if s.endswith('个月'):
            return int(s[:-2] or '0') * 28
        if s.endswith('周'):
            return int(s[:-1] or '0') * 7
        if s.endswith('天'):
            return max(0, int(s[:-1] or '0'))
        # English short formats
        if s.endswith('w'):
            return int(s[:-1] or '0') * 7
        if s.endswith('m'):
            return int(s[:-1] or '0') * 28
        return max(0, int(s))
    except ValueError:
        return 0


def resolve_template_offsets(items):
    """Convert relative offsets to absolute offset_days from project start.

    Input: [('name', relative_offset), ...]
    Output: [('name', absolute_offset_days), ...]
    """
    result = []
    cumulative = 0
    for name, offset in items:
        cumulative += parse_offset(offset)
        result.append((name, cumulative))
    return result
