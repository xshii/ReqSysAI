from flask import Blueprint

project_bp = Blueprint('project', __name__)

from app.project import routes  # noqa: E402, F401
from app.project import routes_risk  # noqa: E402, F401
from app.project import routes_member  # noqa: E402, F401
from app.project import routes_knowledge  # noqa: E402, F401
from app.project import routes_permission  # noqa: E402, F401
from app.project import routes_meeting  # noqa: E402, F401
