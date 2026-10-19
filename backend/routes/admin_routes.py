"""Admin-only: user management (agents + admins) and audit log."""
from flask import Blueprint, jsonify, request, g

from auth import require_role
from database import get_conn
from users import UserRepository
from utils import fmt_local

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _b(v) -> bool:
    return v in (True, "true", "1", 1)


@bp.get("/agents")
@require_role("admin")
def list_agents():
    return jsonify(UserRepository(g.user).list_agents())


@bp.get("/admins")
@require_role("admin")
def list_admins():
    return jsonify(UserRepository(g.user).list_admins())


@bp.post("/users")
@require_role("admin")
def create_user():
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).create_user(b.get("name"), b.get("role") or "agent",
                                                       b.get("username") or None, b.get("password") or None)), 201


@bp.put("/users/<username>")
@require_role("admin")
def update_user(username):
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).update_user(username, b.get("name") or None, b.get("username") or None,
                                                       b.get("password") or None, _b(b.get("reset_password"))))


@bp.get("/users/<username>/role-preview")
@require_role("admin")
def role_preview(username):
    a = request.args
    p = UserRepository(g.user).role_preview(username, a.get("role"), a.get("reassign_to") or None, _b(a.get("delete_tasks")))
    p.pop("plan", None)
    return jsonify(p)


@bp.post("/users/<username>/role")
@require_role("admin")
def change_role(username):
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).change_role(username, b.get("role"), b.get("reassign_to") or None,
                                                       _b(b.get("delete_tasks"))))


@bp.get("/users/<username>/delete-preview")
@require_role("admin")
def delete_preview(username):
    a = request.args
    p = UserRepository(g.user).delete_preview(username, a.get("reassign_to") or None, _b(a.get("delete_tasks")))
    p.pop("plan", None)
    return jsonify(p)


@bp.post("/users/<username>/delete")
@require_role("admin")
def delete_user(username):
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).delete_user(username, b.get("reassign_to") or None, _b(b.get("delete_tasks"))))


@bp.get("/audit")
@require_role("admin")
def audit_log():
    with get_conn() as conn:
        rows = conn.execute("""SELECT a.action, a.detail, a.created_at, u.display_name FROM audit_log a
                               LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 300""").fetchall()
    return jsonify([{**dict(r), "created_local": fmt_local(r["created_at"])} for r in rows])
