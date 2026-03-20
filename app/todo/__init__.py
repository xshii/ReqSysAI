from flask import Blueprint

todo_bp = Blueprint('todo', __name__)

from app.todo import routes  # noqa: E402, F401
