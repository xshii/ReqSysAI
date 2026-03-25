"""Centralized AI prompt management.

All prompts are stored in prompts.yml (admin-editable via backend).
This module provides read/write functions only.
"""
import os

import yaml
from flask import current_app

# Human-readable labels for admin UI
LABELS = {
    'system_prompt': '全局系统提示词',
    'requirement_parse': '需求分解',
    'todo_recommend': 'Todo 智能推荐',
    'weekly_report': '项目周报分析',
    'personal_weekly': '个人周报生成',
    'incentive_polish_comment': '激励评语润色',
    'incentive_polish_desc': '激励事迹润色',
    'incentive_generate': '激励事迹生成',
    'risk_scan': 'AI 风险识别',
    'smart_assign': '智能指派',
    'daily_standup': '每日站会摘要',
    'emotion_predict': '情绪预测',
    'personal_efficiency': '个人效率分析',
    'recurring_recommend': '周期任务推荐',
    'incentive_recommend': 'AI 激励推荐',
    'req_quality_check': '需求质量检查',
    'meeting_extract': '会议纪要提取',
    'aar_extract_issues': 'AAR遗留问题提取',
}


def _prompts_path():
    return os.path.join(current_app.root_path, '..', 'prompts.yml')


def _load_prompts():
    """Load all prompts from prompts.yml."""
    path = _prompts_path()
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def get_prompt(key):
    """Get prompt by key from prompts.yml."""
    return _load_prompts().get(key, '')


def get_all_prompts():
    """Get all prompts. Returns dict of {key: text}."""
    data = _load_prompts()
    result = {}
    for key in LABELS:
        result[key] = data.get(key, '')
    return result


def save_prompt(key, text):
    """Save a single prompt to prompts.yml."""
    data = _load_prompts()
    data[key] = text
    path = _prompts_path()
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, width=1000)


def save_all_prompts(prompts_dict):
    """Replace all prompts in prompts.yml."""
    path = _prompts_path()
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(prompts_dict, f, allow_unicode=True, default_flow_style=False, width=1000)
