from flask import Blueprint

project_bp = Blueprint('project', __name__)

from app.project import routes  # noqa: E402, F401
