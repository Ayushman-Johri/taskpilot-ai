from flask import Blueprint, request, jsonify, g

from auth import require
from config import STATUSES, PRIORITIES
from repository import TaskRepository

bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")


@bp.get("/meta")
@require()
def meta():
    return jsonify({"statuses": STATUSES, "priorities": list(PRIORITIES)})


@bp.get("")
@require("tasks.view_all", "tasks.view_own", any_of=True)
def list_tasks():
    a = request.args
    return jsonify(TaskRepository(g.user).list_tasks(
        status=a.get("status") or None, priority=a.get("priority") or None, agent=a.get("agent") or None,
        overdue_only=a.get("overdue_only") == "true", pending_only=a.get("pending_only") == "true",
        search=(a.get("q") or "").strip() or None, mine=a.get("mine") == "true"))


@bp.get("/<int:task_id>")
@require("tasks.view_all", "tasks.view_own", any_of=True)
def get_task(task_id):
    repo = TaskRepository(g.user)
    return jsonify({"task": repo.get_task(task_id), "history": repo.task_history(task_id)})


@bp.post("")
@require("tasks.create")
def create_task():
    return jsonify(TaskRepository(g.user).create_task(request.get_json(silent=True) or {})), 201


@bp.put("/<int:task_id>")
@require("tasks.edit")
def edit_task(task_id):
    return jsonify(TaskRepository(g.user).update_task(task_id, request.get_json(silent=True) or {}))


@bp.delete("/<int:task_id>")
@require("tasks.delete")
def delete_task(task_id):
    TaskRepository(g.user).delete_task(task_id)
    return jsonify({"ok": True})


@bp.patch("/<int:task_id>/progress")
@require("tasks.update_own")
def update_progress(task_id):
    return jsonify(TaskRepository(g.user).update_progress(task_id, request.get_json(silent=True) or {}))
