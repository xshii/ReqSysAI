from flask import Blueprint

requirement_bp = Blueprint('requirement', __name__)

from app.requirement import routes  # noqa: E402, F401
