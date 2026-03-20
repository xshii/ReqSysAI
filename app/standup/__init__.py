from flask import Blueprint

standup_bp = Blueprint('standup', __name__)

from app.standup import routes  # noqa: E402, F401
