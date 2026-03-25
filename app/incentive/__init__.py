from flask import Blueprint

incentive_bp = Blueprint('incentive', __name__)
from app.incentive import routes  # noqa
