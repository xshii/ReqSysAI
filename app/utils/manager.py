# -*- coding: utf-8 -*-
"""Manager field normalization: ensure employee_id has pinyin prefix."""
import re

from app.models.user import User
from app.utils.pinyin import pinyin_initial

EID_FULL_RE = re.compile(r'^[a-z](00\d{6}|\d00\d{7})$')
EID_NUM_RE = re.compile(r'^(00\d{6}|\d00\d{7})$')


def normalize_manager(raw):
    """Normalize a manager string to '姓名 完整工号' format.

    Accepts:
      - '张三 a00123456'  → as-is
      - '张三 00123456'   → auto-prepend pinyin initial of '张三'
      - '张三'            → lookup system user, fill in employee_id
      - ''                → returns None

    Returns (manager_str, error_msg). If error_msg is not None, normalization failed.
    """
    if not raw or not raw.strip():
        return None, None

    raw = raw.strip()
    parts = raw.rsplit(' ', 1)

    if len(parts) == 2:
        mgr_name, mgr_eid = parts[0].strip(), parts[1].strip()
        if EID_FULL_RE.match(mgr_eid):
            return raw, None  # already complete
        if EID_NUM_RE.match(mgr_eid):
            # Missing prefix, generate from manager name
            prefix = pinyin_initial(mgr_name)
            if prefix:
                return f'{mgr_name} {prefix}{mgr_eid}', None
            return None, '无法从主管姓名生成工号首字母'

    # Try matching system user by full input or name part
    mgr_user = User.query.filter_by(name=raw, is_active=True).first()
    if not mgr_user and len(parts) == 2:
        mgr_user = User.query.filter_by(name=parts[0].strip(), is_active=True).first()
    if mgr_user:
        return f'{mgr_user.name} {mgr_user.employee_id}', None

    return None, '主管未找到，请输入 姓名 工号'
