from flask import Blueprint, jsonify, g

from auth import require
from repository import TaskRepository

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.get("/team")
@require("dashboard.team")
def team_dashboard():
    return jsonify(TaskRepository(g.user).team_dashboard())


@bp.get("/me")
@require("tasks.view_own")
def my_dashboard():
    return jsonify(TaskRepository(g.user).my_dashboard())
