"""Roles & permissions management (stored in roles + role_permissions tables).
Requires roles.manage, except listing (also allowed for users.view / users.create to pick a role).
Rules: the locked 'Admin' role cannot be edited or deleted; system roles cannot be deleted;
a role in use cannot be deleted; you can only grant permissions you hold yourself (+ basic own-work ones);
at least one active user must keep roles.manage."""
import re

from auth import User
from database import get_conn, audit, role_permissions, set_role_permissions, users_with_permission
from errors import BadRequest, Conflict, Forbidden, NotFound
from permissions import BASE_GRANTABLE, LABELS, normalize
from utils import now_utc, to_iso

ROLE_NAME_RE = re.compile(r"^[\w][\w .&'\-]{1,39}$", re.UNICODE)


class RoleRepository:
    def __init__(self, user: User):
        self.user = user

    def _need_manage(self):
        if not self.user.has("roles.manage"):
            raise Forbidden("You don't have permission to manage roles.")

    def _check_grantable(self, perms):
        missing = set(perms) - set(self.user.permissions) - BASE_GRANTABLE
        if missing:
            raise Forbidden("You can only grant permissions you have yourself. Missing: "
                            + ", ".join(LABELS[p] for p in sorted(missing)) + ".")

    @staticmethod
    def _clean(name, description):
        name = re.sub(r"\s+", " ", str(name or "")).strip()
        if not ROLE_NAME_RE.match(name):
            raise BadRequest("Role name must be 2-40 characters.")
        return name, str(description or "").strip()[:200]

    def list_roles(self) -> list:
        if not self.user.has_any("roles.manage", "users.view", "users.create"):
            raise Forbidden("You don't have permission to view roles.")
        with get_conn() as conn:
            rows = conn.execute("""SELECT r.*, (SELECT COUNT(*) FROM users u WHERE u.role_id=r.id AND u.is_active=1) AS user_count
                                   FROM roles r ORDER BY r.is_system DESC, r.name""").fetchall()
            out = []
            for r in rows:
                perms = role_permissions(conn, r["id"])
                out.append({"id": r["id"], "name": r["name"], "description": r["description"], "is_system": bool(r["is_system"]),
                            "locked": bool(r["locked"]), "user_count": r["user_count"], "permissions": sorted(perms),
                            "grantable": not (perms - set(self.user.permissions) - BASE_GRANTABLE)})
        return out

    def create_role(self, name, description, permissions) -> dict:
        self._need_manage()
        name, description = self._clean(name, description)
        perms = normalize(permissions)
        if not perms:
            raise BadRequest("Select at least one permission.")
        self._check_grantable(perms)
        with get_conn() as conn:
            if conn.execute("SELECT 1 FROM roles WHERE name=? COLLATE NOCASE", (name,)).fetchone():
                raise Conflict(f"A role named '{name}' already exists.")
            rid = conn.execute("INSERT INTO roles(name, description, created_at) VALUES (?,?,?)",
                               (name, description, to_iso(now_utc()))).lastrowid
            set_role_permissions(conn, rid, perms)
            conn.execute("DELETE FROM ai_cache")
        audit(self.user.id, "role_create", f"{name}: {', '.join(sorted(perms))}")
        return {"id": rid, "name": name, "permissions": sorted(perms)}

    def update_role(self, role_id, name=None, description=None, permissions=None) -> dict:
        self._need_manage()
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM roles WHERE id=?", (int(role_id),)).fetchone()
            if not row:
                raise NotFound("Role not found.")
            if row["locked"]:
                raise Forbidden(f"The '{row['name']}' role is locked and cannot be changed.")
            old_perms = role_permissions(conn, row["id"])
            self._check_grantable(old_perms)
            new_name, new_desc = self._clean(name if name is not None else row["name"],
                                             description if description is not None else row["description"])
            if new_name.lower() != row["name"].lower() and conn.execute(
                    "SELECT 1 FROM roles WHERE name=? COLLATE NOCASE AND id != ?", (new_name, row["id"])).fetchone():
                raise Conflict(f"A role named '{new_name}' already exists.")
            if row["is_system"] and new_name != row["name"]:
                raise BadRequest("System roles cannot be renamed.")
            perms = old_perms if permissions is None else normalize(permissions)
            if not perms:
                raise BadRequest("Select at least one permission.")
            self._check_grantable(perms)
            if "roles.manage" in old_perms and "roles.manage" not in perms:
                in_role = {r[0] for r in conn.execute("SELECT id FROM users WHERE role_id=? AND is_active=1", (row["id"],))}
                if not set(users_with_permission(conn, "roles.manage")) - in_role:
                    raise BadRequest("At least one active user must keep the 'manage roles' permission.")
            if self.user.role_id == row["id"] and "roles.manage" not in perms:
                raise BadRequest("You cannot remove 'manage roles' from your own role.")
            if "tasks.update_own" in old_perms and "tasks.update_own" not in perms:
                busy = conn.execute("""SELECT COUNT(*) FROM tasks t JOIN users u ON u.id=t.assigned_to
                                       WHERE u.role_id=? AND u.is_active=1 AND t.status != 'Completed'""", (row["id"],)).fetchone()[0]
                if busy:
                    raise BadRequest(f"Users with this role still have {busy} pending task(s). Reassign them before removing "
                                     f"'{LABELS['tasks.update_own']}'.")
            conn.execute("UPDATE roles SET name=?, description=? WHERE id=?", (new_name, new_desc, row["id"]))
            set_role_permissions(conn, row["id"], perms)
            conn.execute("DELETE FROM ai_cache")
        added, removed = sorted(perms - old_perms), sorted(old_perms - perms)
        audit(self.user.id, "role_update", f"{new_name}: +{added} -{removed}")
        return {"id": row["id"], "name": new_name, "permissions": sorted(perms), "added": added, "removed": removed}

    def delete_role(self, role_id) -> dict:
        self._need_manage()
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM roles WHERE id=?", (int(role_id),)).fetchone()
            if not row:
                raise NotFound("Role not found.")
            if row["is_system"]:
                raise Forbidden("System roles cannot be deleted.")
            self._check_grantable(role_permissions(conn, row["id"]))
            used = conn.execute("SELECT COUNT(*) FROM users WHERE role_id=? AND is_active=1", (row["id"],)).fetchone()[0]
            if used:
                raise BadRequest(f"{used} user(s) still have this role. Change their role first.")
            conn.execute("UPDATE users SET role_id=(SELECT id FROM roles WHERE name='Agent') WHERE role_id=? AND is_active=0", (row["id"],))
            conn.execute("DELETE FROM roles WHERE id=?", (row["id"],))
        audit(self.user.id, "role_delete", row["name"])
        return {"id": row["id"], "name": row["name"]}
