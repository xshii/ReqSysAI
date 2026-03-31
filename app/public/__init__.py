from flask import Blueprint

public_bp = Blueprint('public', __name__)

from app.public import routes  # noqa: E402, F401
