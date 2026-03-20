import json
import logging

import requests
from flask import current_app

logger = logging.getLogger(__name__)

REQUIREMENT_SYSTEM_PROMPT = (
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
)


def call_ollama(prompt, system_prompt=None, messages=None):
    """Common Ollama /api/chat call. Returns (parsed_json, raw_text) or (None, None).

    Use either:
      - prompt + optional system_prompt (simple call)
      - messages (multi-turn conversation)
    """
    base_url = current_app.config['OLLAMA_BASE_URL']
    model = current_app.config['OLLAMA_MODEL']

    if messages is None:
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': prompt})

    try:
        resp = requests.post(
            f'{base_url}/api/chat',
            json={'model': model, 'messages': messages, 'stream': False},
            timeout=current_app.config.get('AI_TIMEOUT', 120),
            proxies={'http': '', 'https': ''},
        )
        resp.raise_for_status()
        raw = resp.json().get('message', {}).get('content', '')
        return _extract_json(raw), raw
    except requests.RequestException:
        logger.exception('Ollama API error')
        return None, None


def parse_requirement(text):
    """Parse requirement from text."""
    return call_ollama(text, system_prompt=REQUIREMENT_SYSTEM_PROMPT)


def refine_requirement(original_text, previous_result, feedback):
    """Re-parse with PM's feedback as multi-turn conversation."""
    return call_ollama(None, messages=[
        {'role': 'system', 'content': REQUIREMENT_SYSTEM_PROMPT},
        {'role': 'user', 'content': original_text},
        {'role': 'assistant', 'content': json.dumps(previous_result, ensure_ascii=False)},
        {'role': 'user', 'content': f'以上解析结果不太对，请根据我的意见重新解析：{feedback}'},
    ])


def extract_text_from_docx(file_storage):
    """Extract plain text from uploaded .docx file."""
    from docx import Document
    doc = Document(file_storage)
    return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_json(text):
    """Try to extract JSON from LLM response (may be wrapped in markdown)."""
    text = text.strip()
    if '```json' in text:
        text = text.split('```json', 1)[1]
    if '```' in text:
        text = text.split('```', 1)[0]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning('Failed to parse AI JSON output: %s', text[:200])
        return None
