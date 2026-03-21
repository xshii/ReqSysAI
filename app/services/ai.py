import json
import logging
import socket
import subprocess
import time

import requests
from flask import current_app

logger = logging.getLogger(__name__)


def _is_port_open(port, host='127.0.0.1', timeout=2):
    """Check if a local port is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ensure_ssh_tunnel():
    """Check SSH tunnel and establish if needed. Returns (ok, error_msg)."""
    ssh_enabled = current_app.config.get('OLLAMA_SSH_ENABLED', False)
    ssh_host = current_app.config.get('OLLAMA_SSH_HOST', '')
    local_port = current_app.config.get('OLLAMA_SSH_LOCAL_PORT', 11434)

    if not ssh_enabled or not ssh_host:
        # No SSH configured, just check if Ollama is reachable
        if _is_port_open(local_port):
            return True, None
        return False, f'Ollama 服务不可达 (127.0.0.1:{local_port})，请检查服务是否启动'

    # SSH mode: check if tunnel is already up
    if _is_port_open(local_port):
        return True, None

    # Try to establish SSH tunnel in background
    logger.info('SSH tunnel not found, establishing via %s ...', ssh_host)
    try:
        subprocess.Popen(
            ['ssh', '-f', '-N', '-L', f'{local_port}:127.0.0.1:{local_port}', ssh_host],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        # Wait briefly for tunnel to establish
        for _ in range(5):
            time.sleep(1)
            if _is_port_open(local_port):
                logger.info('SSH tunnel established via %s', ssh_host)
                return True, None
        return False, f'SSH 隧道建立超时，请手动执行: ssh -f -N -L {local_port}:127.0.0.1:{local_port} {ssh_host}'
    except FileNotFoundError:
        return False, 'ssh 命令不可用，请检查系统 PATH'
    except Exception as e:
        return False, f'SSH 隧道建立失败: {e}'

def _get_requirement_prompt():
    from app.services.prompts import get_prompt
    return get_prompt('requirement_parse')


def check_ollama_status():
    """Check Ollama connectivity. Returns (ok, error_msg)."""
    return _ensure_ssh_tunnel()


def call_ollama(prompt, system_prompt=None, messages=None):
    """Common Ollama /api/chat call. Returns (parsed_json, raw_text) or (None, None).

    Use either:
      - prompt + optional system_prompt (simple call)
      - messages (multi-turn conversation)
    """
    # Check SSH tunnel / connectivity first
    ok, err_msg = _ensure_ssh_tunnel()
    if not ok:
        logger.error('Ollama unreachable: %s', err_msg)
        return None, err_msg

    base_url = current_app.config['OLLAMA_BASE_URL']
    model = current_app.config['OLLAMA_MODEL']

    if messages is None:
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': prompt})

    # Build input text for logging
    input_text = prompt or ''
    if not input_text and messages:
        input_text = ' '.join(m.get('content', '') for m in messages if m.get('role') == 'user')

    try:
        resp = requests.post(
            f'{base_url}/api/chat',
            json={'model': model, 'messages': messages, 'stream': False},
            timeout=current_app.config.get('AI_TIMEOUT', 120),
            proxies={'http': '', 'https': ''},
        )
        resp.raise_for_status()
        raw = resp.json().get('message', {}).get('content', '')
        _log_ai_call(input_text, raw)
        return _extract_json(raw), raw
    except requests.RequestException:
        logger.exception('Ollama API error')
        return None, None


def _log_ai_call(raw_input, ai_output):
    """Record AI call to AIParseLog for usage tracking."""
    try:
        from flask_login import current_user
        if not current_user or not current_user.is_authenticated:
            return
        from app.models.ai_log import AIParseLog
        from app.extensions import db
        max_len = current_app.config.get('AI_INPUT_MAX', 5000)
        log = AIParseLog(
            input_type='api_call',
            raw_input=(raw_input or '')[:max_len],
            ai_output=ai_output,
            created_by=current_user.id,
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        logger.debug('Failed to log AI call', exc_info=True)


def parse_requirement(text):
    """Parse requirement from text."""
    return call_ollama(text, system_prompt=_get_requirement_prompt())


def refine_requirement(original_text, previous_result, feedback):
    """Re-parse with PM's feedback as multi-turn conversation."""
    return call_ollama(None, messages=[
        {'role': 'system', 'content': _get_requirement_prompt()},
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
