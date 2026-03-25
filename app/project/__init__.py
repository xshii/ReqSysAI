from flask import Blueprint

project_bp = Blueprint('project', __name__)

from app.project import (
    routes,  # noqa: E402, F401
    routes_knowledge,  # noqa: E402, F401
    routes_meeting,  # noqa: E402, F401
    routes_member,  # noqa: E402, F401
    routes_permission,  # noqa: E402, F401
    routes_risk,  # noqa: E402, F401
)
