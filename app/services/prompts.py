"""Centralized AI prompt management.

Defaults are hardcoded here. Overrides come from prompts.yml (admin-editable).
"""
import os
import yaml
from flask import current_app

# ---- Default prompts ----

DEFAULTS = {
    'requirement_parse': (
        '你是一个需求分析助手。用户会给你聊天记录、会议纪要或需求文档，'
        '你需要从中提取软件需求信息。\n'
        '请严格按以下 JSON 格式返回，不要返回任何其他内容：\n'
        '{"title":"需求标题(20字以内)","description":"需求详细描述",'
        '"priority":"high或medium或low","estimate_days":预估总工期(人天,数字),'
        '"subtasks":[{"title":"子需求标题","estimate_days":预估人天}]}\n'
        '规则：\n'
        '1. 提取最主要的一个需求作为父需求\n'
        '2. priority根据紧急程度判断\n'
        '3. subtasks拆分为可独立交付的子需求（不是开发任务），每个子需求预估人天\n'
        '4. estimate_days为所有子需求人天之和\n'
        '5. 如果内容简单无需拆分，subtasks可以为空数组'
    ),
    'todo_recommend': (
        '根据以下信息，推荐今天应该新增的任务。\n'
        '要求：\n'
        '1. 根据需求优先级和截止日期排序，紧急的优先\n'
        '2. 参考近一周完成情况，推进未完成的需求\n'
        '3. 不要重复已有任务\n'
        '4. 每个任务拆分为可执行的子项\n'
        '5. 返回 JSON 数组，格式如下，只返回 JSON：\n'
        '[{"title":"任务标题","req_number":"REQ-001","items":["子项1","子项2"]}]'
    ),
    'weekly_report': (
        '根据以下{project_name}本周工作数据，生成分析内容。\n'
        '严格返回 JSON，不要返回其他内容：\n'
        '{{"summary":"一句话总结本周整体进展",'
        '"risks":["风险或问题1","风险或问题2"],'
        '"plan":["下周计划1","下周计划2"]}}\n'
        '规则：\n'
        '- summary 不超过50字\n'
        '- risks 基于超期需求、资源不足等实际数据分析，没有风险写"暂无"\n'
        '- plan 基于未完成需求和截止日期推导，具体到需求编号\n'
        '- 不要编造数据'
    ),
    'personal_weekly': (
        '根据以下个人本周工作数据，生成一份简洁的中文个人周报。\n'
        '要求：\n'
        '1. 本周完成的工作（按需求分组）\n'
        '2. 进行中的工作\n'
        '3. 下周计划\n'
        '4. 遇到的问题/需要的支持\n'
        '用 Markdown 格式，简洁专业。'
    ),
    'incentive_polish_comment': (
        '请润色以下激励评语，保持原意，语言精炼正式，不超过150字：'
    ),
    'incentive_polish_desc': (
        '请润色以下激励事迹描述，语言生动正式，突出贡献和价值，不超过300字：'
    ),
    'incentive_generate': (
        '以下是团队成员近30天的工作数据：\n\n{{context}}\n\n'
        '请根据以上信息，撰写一段激励事迹描述（激励类别：{{category}}），'
        '突出他们的贡献和价值，语言正式生动，不超过300字。'
        '只返回事迹描述文本，不要加标题或格式。'
    ),
}

# Human-readable labels for admin UI
LABELS = {
    'requirement_parse': '需求解析',
    'todo_recommend': 'Todo 智能推荐',
    'weekly_report': '项目周报分析',
    'personal_weekly': '个人周报生成',
    'incentive_polish_comment': '激励评语润色',
    'incentive_polish_desc': '激励事迹润色',
    'incentive_generate': '激励事迹生成',
}


def _prompts_path():
    return os.path.join(current_app.root_path, '..', 'prompts.yml')


def _load_overrides():
    path = _prompts_path()
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def get_prompt(key):
    """Get prompt by key. Override from prompts.yml, fallback to default."""
    overrides = _load_overrides()
    return overrides.get(key, DEFAULTS.get(key, ''))


def get_all_prompts():
    """Get all prompts with overrides applied. Returns dict of {key: text}."""
    overrides = _load_overrides()
    result = {}
    for key in DEFAULTS:
        result[key] = overrides.get(key, DEFAULTS[key])
    return result


def save_prompt(key, text):
    """Save a single prompt override to prompts.yml."""
    overrides = _load_overrides()
    if text.strip() == DEFAULTS.get(key, '').strip():
        overrides.pop(key, None)  # Remove if same as default
    else:
        overrides[key] = text
    path = _prompts_path()
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(overrides, f, allow_unicode=True, default_flow_style=False, width=1000)


def save_all_prompts(prompts_dict):
    """Save all prompt overrides to prompts.yml."""
    overrides = {}
    for key, text in prompts_dict.items():
        if key in DEFAULTS and text.strip() != DEFAULTS[key].strip():
            overrides[key] = text
    path = _prompts_path()
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(overrides, f, allow_unicode=True, default_flow_style=False, width=1000)
