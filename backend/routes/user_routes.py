"""Users, roles, permission catalogue and audit log."""
from flask import Blueprint, jsonify, request, g

from auth import require
from database import get_conn
from permissions import catalogue
from roles import RoleRepository
from users import UserRepository
from utils import fmt_local

bp = Blueprint("users", __name__, url_prefix="/api")


def _b(v) -> bool:
    return v in (True, "true", "1", 1)


# ---- users ----------------------------------------------------------------------
@bp.get("/users")
@require("users.view")
def list_users():
    return jsonify(UserRepository(g.user).list_users())


@bp.get("/users/assignees")
@require("tasks.create", "tasks.edit", "tasks.view_all", "users.view", any_of=True)
def list_assignees():
    return jsonify(UserRepository(g.user).list_assignees())


@bp.post("/users")
@require("users.create")
def create_user():
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).create_user(b.get("name"), b.get("role") or "Agent",
                                                       b.get("username") or None, b.get("password") or None)), 201


@bp.put("/users/<username>")
@require()
def update_user(username):
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).update_user(username, b.get("name") or None, b.get("username") or None,
                                                       b.get("password") or None, _b(b.get("reset_password"))))


@bp.get("/users/<username>/role-preview")
@require("roles.manage")
def role_preview(username):
    a = request.args
    p = UserRepository(g.user).role_preview(username, a.get("role"), a.get("reassign_to") or None, _b(a.get("delete_tasks")))
    p.pop("plan", None)
    return jsonify(p)


@bp.post("/users/<username>/role")
@require("roles.manage")
def change_role(username):
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).change_role(username, b.get("role"), b.get("reassign_to") or None, _b(b.get("delete_tasks"))))


@bp.get("/users/<username>/delete-preview")
@require("users.delete")
def delete_preview(username):
    a = request.args
    p = UserRepository(g.user).delete_preview(username, a.get("reassign_to") or None, _b(a.get("delete_tasks")))
    p.pop("plan", None)
    return jsonify(p)


@bp.post("/users/<username>/delete")
@require("users.delete")
def delete_user(username):
    b = request.get_json(silent=True) or {}
    return jsonify(UserRepository(g.user).delete_user(username, b.get("reassign_to") or None, _b(b.get("delete_tasks"))))


# ---- roles & permissions --------------------------------------------------------------
@bp.get("/permissions")
@require()
def permissions():
    return jsonify(catalogue())


@bp.get("/roles")
@require("roles.manage", "users.view", "users.create", any_of=True)
def list_roles():
    return jsonify(RoleRepository(g.user).list_roles())


@bp.post("/roles")
@require("roles.manage")
def create_role():
    b = request.get_json(silent=True) or {}
    return jsonify(RoleRepository(g.user).create_role(b.get("name"), b.get("description"), b.get("permissions") or [])), 201


@bp.put("/roles/<int:role_id>")
@require("roles.manage")
def update_role(role_id):
    b = request.get_json(silent=True) or {}
    return jsonify(RoleRepository(g.user).update_role(role_id, b.get("name"), b.get("description"), b.get("permissions")))


@bp.delete("/roles/<int:role_id>")
@require("roles.manage")
def delete_role(role_id):
    return jsonify(RoleRepository(g.user).delete_role(role_id))


# ---- audit -------------------------------------------------------------------------
@bp.get("/audit")
@require("audit.view")
def audit_log():
    with get_conn() as conn:
        rows = conn.execute("""SELECT a.action, a.detail, a.created_at, u.display_name FROM audit_log a
                               LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 300""").fetchall()
    return jsonify([{**dict(r), "created_local": fmt_local(r["created_at"])} for r in rows])
