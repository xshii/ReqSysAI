import json
import os

# Static config keys — read from instance/site_config.json, write back on set()
from app.constants import SITE_CONFIG_DEFAULTS as _CONFIG_DEFAULTS
from app.extensions import db

_CONFIG_KEYS = set(_CONFIG_DEFAULTS.keys())

_config_cache = None


def _config_path():
    from flask import current_app
    return os.path.join(current_app.instance_path, 'site_config.json')


def _load_config():
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    path = _config_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            _config_cache = json.load(f)
    else:
        _config_cache = {}
    return _config_cache


def _save_config(data):
    global _config_cache
    _config_cache = data
    path = _config_path()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SiteSetting(db.Model):
    """Key-value store. Static configs in instance/site_config.json, dynamic in DB."""
    __tablename__ = 'site_settings'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, default='')

    @staticmethod
    def get(key, default=''):
        # Static config: JSON → DB → built-in default
        if key in _CONFIG_KEYS:
            try:
                cfg = _load_config()
                val = cfg.get(key)
                if val is not None and val != '':
                    return val
            except Exception:
                pass
            # Fallback to DB (legacy data)
            row = SiteSetting.query.get(key)
            if row and row.value:
                return row.value
            # Built-in default
            return _CONFIG_DEFAULTS.get(key, default)
        # Dynamic: read from DB
        row = SiteSetting.query.get(key)
        return row.value if row and row.value else default

    @staticmethod
    def set(key, value):
        # Static config: write to JSON file
        if key in _CONFIG_KEYS:
            try:
                cfg = _load_config()
                cfg[key] = value
                _save_config(cfg)
                return
            except Exception:
                pass
        # Dynamic: write to DB
        row = SiteSetting.query.get(key)
        if row:
            row.value = value
        else:
            db.session.add(SiteSetting(key=key, value=value))
        db.session.commit()

    @staticmethod
    def reload_config():
        """Force reload config from disk (after manual file edit)."""
        global _config_cache
        _config_cache = None
