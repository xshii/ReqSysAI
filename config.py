import os
from pathlib import Path

import yaml

_cfg_path = Path(__file__).parent / 'config.yml'
_yml = yaml.safe_load(_cfg_path.read_text(encoding='utf-8')) if _cfg_path.exists() else {}

# config.local.yml overrides config.yml (gitignored, for deployment customization)
_local_path = Path(__file__).parent / 'config.local.yml'
if _local_path.exists():
    _local = yaml.safe_load(_local_path.read_text(encoding='utf-8')) or {}
    for section, values in _local.items():
        if isinstance(values, dict) and isinstance(_yml.get(section), dict):
            _yml[section].update(values)
        else:
            _yml[section] = values


_basedir = Path(__file__).parent


def _resolve_db_url():
    url = os.getenv('DATABASE_URL', _yml.get('app', {}).get('database_url', 'sqlite:///instance/reqsys.db'))
    if url.startswith('sqlite:///') and not url.startswith('sqlite:////'):
        url = f'sqlite:///{_basedir / url[len("sqlite:///"):]}'
    return url


class Config:
    # App
    SECRET_KEY = os.getenv('SECRET_KEY', _yml.get('app', {}).get('secret_key', 'dev-only-key'))
    SQLALCHEMY_DATABASE_URI = _resolve_db_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = _yml.get('app', {}).get('session_timeout', 600)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Auth
    SSO_URL = _yml.get('auth', {}).get('sso_url', '')
    DEFAULT_ROLE = _yml.get('auth', {}).get('default_role', 'DE')

    # Ollama
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', _yml.get('ollama', {}).get('base_url', 'http://127.0.0.1:11434'))
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', _yml.get('ollama', {}).get('model', 'qwen2.5'))
    OLLAMA_SSH_ENABLED = _yml.get('ollama', {}).get('ssh_enabled', False)
    OLLAMA_SSH_HOST = _yml.get('ollama', {}).get('ssh_host', '')
    OLLAMA_SSH_LOCAL_PORT = _yml.get('ollama', {}).get('ssh_local_port', 11434)

    # App tuning
    TODO_KEEP_DAYS = _yml.get('app', {}).get('todo_keep_days', 7)
    OVERDUE_WARN_DAYS = _yml.get('app', {}).get('overdue_warn_days', 1)
    OVERDUE_DANGER_DAYS = _yml.get('app', {}).get('overdue_danger_days', 3)
    AI_INPUT_MAX = _yml.get('app', {}).get('ai_input_max', 5000)
    AI_TIMEOUT = _yml.get('app', {}).get('ai_timeout', 120)

    # Roles & admin from YAML
    ROLES = _yml.get('roles', [])
    HIDDEN_ROLES = [r['name'] for r in ROLES if r.get('hidden')]
    ADMIN_CONFIG = _yml.get('admin', {})


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestConfig,
}
