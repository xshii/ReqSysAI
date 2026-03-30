"""Unified JSON API response helper."""
from flask import jsonify


def api_ok(msg='ok', **kwargs):
    """Success response."""
    return jsonify(ok=True, msg=msg, **kwargs)


def api_err(msg='error', status=400, **kwargs):
    """Error response."""
    return jsonify(ok=False, msg=msg, **kwargs), status
