"""Centralized constants – eliminate magic strings & numbers across the codebase."""

# ---------------------------------------------------------------------------
# Todo statuses
# ---------------------------------------------------------------------------
TODO_STATUS_TODO = 'todo'
TODO_STATUS_DONE = 'done'

# Todo categories (work counts for project investment, others don't)
TODO_CAT_WORK = 'work'
TODO_CAT_TEAM = 'team'
TODO_CAT_PERSONAL = 'personal'
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
INCENTIVE_SOURCE_LABELS = {
    'instant': '及时激励',
    'special': '专项激励',
    'knowledge': '知识管理激励',
    'improvement': '持续改进激励',
}
