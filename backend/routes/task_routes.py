from flask import Blueprint, request, jsonify, g

from auth import require_role
from config import STATUSES, PRIORITIES
from repository import TaskRepository

bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")


@bp.get("/meta")
@require_role()
def meta():
    return jsonify({"statuses": STATUSES, "priorities": list(PRIORITIES)})


@bp.get("")
@require_role()
def list_tasks():
    a = request.args
    return jsonify(TaskRepository(g.user).list_tasks(
        status=a.get("status") or None, priority=a.get("priority") or None,
        agent=(a.get("agent") or None) if g.user.is_admin else None,
        overdue_only=a.get("overdue_only") == "true", pending_only=a.get("pending_only") == "true",
        search=(a.get("q") or "").strip() or None))


@bp.get("/<int:task_id>")
@require_role()
def get_task(task_id):
    repo = TaskRepository(g.user)
    return jsonify({"task": repo.get_task(task_id), "history": repo.task_history(task_id)})


@bp.post("")
@require_role("admin")
def create_task():
    return jsonify(TaskRepository(g.user).create_task(request.get_json(silent=True) or {})), 201


@bp.put("/<int:task_id>")
@require_role("admin")
def edit_task(task_id):
    return jsonify(TaskRepository(g.user).admin_update_task(task_id, request.get_json(silent=True) or {}))


@bp.delete("/<int:task_id>")
@require_role("admin")
def delete_task(task_id):
    TaskRepository(g.user).delete_task(task_id)
    return jsonify({"ok": True})


@bp.patch("/<int:task_id>/progress")
@require_role("agent")
def update_progress(task_id):
    return jsonify(TaskRepository(g.user).agent_update_progress(task_id, request.get_json(silent=True) or {}))
