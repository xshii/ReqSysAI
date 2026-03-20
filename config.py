import os
from pathlib import Path

import yaml

_cfg_path = Path(__file__).parent / 'config.yml'
_yml = yaml.safe_load(_cfg_path.read_text(encoding='utf-8')) if _cfg_path.exists() else {}


_basedir = Path(__file__).parent


def _resolve_db_url():
    url = os.getenv('DATABASE_URL', _yml.get('app', {}).get('database_url', 'sqlite:///data.db'))
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
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', _yml.get('ollama', {}).get('base_url', 'http://192.168.10.50:11434'))
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', _yml.get('ollama', {}).get('model', 'qwen2.5'))

    # Roles & admin from YAML
    ROLES = _yml.get('roles', [])
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
