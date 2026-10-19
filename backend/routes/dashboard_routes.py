from flask import Blueprint, jsonify, g

from auth import require_role
from repository import TaskRepository

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.get("/admin")
@require_role("admin")
def admin_dashboard():
    return jsonify(TaskRepository(g.user).admin_dashboard())


@bp.get("/agent")
@require_role("agent")
def agent_dashboard():
    return jsonify(TaskRepository(g.user).agent_dashboard())
