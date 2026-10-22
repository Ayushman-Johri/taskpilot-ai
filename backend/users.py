"""User management, driven by permissions:
  users.view   -> list people          users.create -> add users      users.edit -> rename / reset password
  users.delete -> delete users         roles.manage -> change a user's role

Privilege-escalation guard: you can only give, or manage someone with, a role whose permissions
you hold yourself (basic "own work" permissions - view/update own tasks, use AI - are always grantable).
Safety: no self role-change or self-delete; at least one active user must keep roles.manage."""
import re
from typing import Optional

from auth import User, hash_password, revoke_all_tokens
from config import MIN_PASSWORD_LEN, STATUS_COMPLETED
from database import get_conn, audit, role_permissions, users_with_permission
from errors import BadRequest, Conflict, Forbidden, NotFound
from notifications import notify
from permissions import BASE_GRANTABLE, LABELS
from repository import resolve_user, TaskRepository, counts, assignees
from utils import generate_password, slugify_username

NAME_RE = re.compile(r"^[\w][\w .'\-]{1,49}$", re.UNICODE)
USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.]{2,29}$")


def resolve_role(conn, role) -> dict:
    raw = str(role or "").strip()
    if not raw:
        raise BadRequest("Role is required.")
    row = (conn.execute("SELECT * FROM roles WHERE id=?", (int(raw),)).fetchone() if raw.isdigit()
           else conn.execute("SELECT * FROM roles WHERE name=? COLLATE NOCASE", (raw,)).fetchone())
    if not row:
        names = [r[0] for r in conn.execute("SELECT name FROM roles ORDER BY name")]
        raise NotFound(f"Role '{raw}' not found. Available roles: {', '.join(names)}.")
    return {**dict(row), "permissions": role_permissions(conn, row["id"])}


class UserRepository:
    def __init__(self, user: User):
        self.user = user

    def _need(self, perm, msg=None):
        if not self.user.has(perm):
            raise Forbidden(msg or "You don't have permission to do this.")

    # ---- guards ---------------------------------------------------------------------
    def _check_grantable(self, perms: set, what: str):
        missing = set(perms) - set(self.user.permissions) - BASE_GRANTABLE
        if missing:
            raise Forbidden(f"You cannot {what}: it includes permissions you don't have "
                            f"({', '.join(LABELS[p] for p in sorted(missing))}).")

    def _target(self, conn, who) -> dict:
        row = resolve_user(conn, who)
        u = dict(conn.execute("""SELECT u.id, u.username, u.display_name, u.role_id, r.name AS role_name
                                 FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=?""", (row["id"],)).fetchone())
        u["permissions"] = role_permissions(conn, u["role_id"])
        return u

    def _not_self(self, target, action):
        if target["id"] == self.user.id:
            raise Forbidden(f"You cannot {action} your own account.")

    @staticmethod
    def _keeps_a_role_manager(conn, losing_user_id: int):
        others = [i for i in users_with_permission(conn, "roles.manage") if i != losing_user_id]
        if not others:
            raise BadRequest("At least one active user must keep the 'manage roles' permission.")

    # ---- validation ----------------------------------------------------------------------
    @staticmethod
    def _clean_name(name) -> str:
        name = re.sub(r"\s+", " ", str(name or "")).strip()
        if not NAME_RE.match(name):
            raise BadRequest("Name must be 2-50 characters (letters, numbers, spaces, . ' -).")
        return name

    @staticmethod
    def _clean_username(username) -> str:
        username = str(username or "").strip().lower()
        if not USERNAME_RE.match(username):
            raise BadRequest("Username must be 3-30 characters, start with a letter, and use only a-z, 0-9, '_' or '.'.")
        return username

    @staticmethod
    def _check_password(password: str) -> str:
        if len(password) < MIN_PASSWORD_LEN:
            raise BadRequest(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        return password

    @staticmethod
    def _name_taken(conn, name, exclude_id=None) -> bool:
        return conn.execute("SELECT 1 FROM users WHERE is_active=1 AND lower(display_name)=lower(?) AND id IS NOT ?",
                            (name, exclude_id)).fetchone() is not None

    @staticmethod
    def _username_taken(conn, username, exclude_id=None) -> bool:
        return conn.execute("SELECT 1 FROM users WHERE lower(username)=? AND id IS NOT ?", (username, exclude_id)).fetchone() is not None

    def _unique_username(self, conn, base: str) -> str:
        if not USERNAME_RE.match(base):
            base = f"user_{base}".strip("_")[:30]
        if not USERNAME_RE.match(base):
            base = "user"
        candidate, i = base, 2
        while self._username_taken(conn, candidate):
            candidate, i = f"{base[:27]}{i}", i + 1
        return candidate

    @staticmethod
    def _end_sessions(conn, user_id: int) -> None:
        revoke_all_tokens(conn, user_id)
        conn.execute("DELETE FROM chat_messages WHERE user_id=?", (user_id,))
        conn.execute("UPDATE ai_actions SET status='cancelled', result='User changed.' WHERE user_id=? AND status='pending'", (user_id,))

    # ---- reads -------------------------------------------------------------------------
    def list_users(self) -> list:
        self._need("users.view")
        tasks = TaskRepository(self.user).list_tasks() if self.user.sees_all_tasks else []
        with get_conn() as conn:
            rows = conn.execute("""SELECT u.id, u.username, u.display_name, u.role_id, r.name AS role_name FROM users u
                                   JOIN roles r ON r.id=u.role_id WHERE u.is_active=1 ORDER BY r.name, u.display_name""").fetchall()
            perms = {r["role_id"]: role_permissions(conn, r["role_id"]) for r in rows}
        out = []
        for r in rows:
            p = perms[r["role_id"]]
            item = {"id": r["id"], "username": r["username"], "display_name": r["display_name"], "role_id": r["role_id"],
                    "role": r["role_name"], "assignable": "tasks.update_own" in p, "is_you": r["id"] == self.user.id,
                    "manageable": not (set(p) - set(self.user.permissions) - BASE_GRANTABLE)}
            if item["assignable"] and self.user.sees_all_tasks:
                item.update(counts([t for t in tasks if t["assigned_to"] == r["id"]]))
            out.append(item)
        return out

    def list_assignees(self) -> list:
        if not self.user.has_any("tasks.create", "tasks.edit", "tasks.view_all", "users.view"):
            raise Forbidden("You don't have permission to see assignees.")
        tasks = TaskRepository(self.user).list_tasks() if self.user.sees_all_tasks else []
        with get_conn() as conn:
            rows = assignees(conn)
        return [{"username": r["username"], "display_name": r["display_name"],
                 "pending": sum(1 for t in tasks if t["assigned_to"] == r["id"] and t["status"] != STATUS_COMPLETED)} for r in rows]

    # ---- create / update ---------------------------------------------------------------------
    def create_user(self, name, role="Agent", username=None, password=None) -> dict:
        self._need("users.create", "You don't have permission to add users.")
        name = self._clean_name(name)
        generated = not password
        password = generate_password() if generated else self._check_password(str(password))
        with get_conn() as conn:
            r = resolve_role(conn, role or "Agent")
            self._check_grantable(r["permissions"], f"give the role '{r['name']}'")
            if self._name_taken(conn, name):
                raise Conflict(f"A user named '{name}' already exists.")
            if username:
                username = self._clean_username(username)
                if self._username_taken(conn, username):
                    raise Conflict(f"Username '{username}' is already taken.")
            else:
                username = self._unique_username(conn, slugify_username(name))
            pw_hash, salt = hash_password(password)
            new_id = conn.execute("INSERT INTO users(username, display_name, role_id, password_hash, salt) VALUES (?,?,?,?,?)",
                                  (username, name, r["id"], pw_hash, salt)).lastrowid
        audit(self.user.id, "user_create", f"{name} ({username}) role {r['name']}")
        return {"id": new_id, "username": username, "display_name": name, "role": r["name"],
                "password": password, "password_generated": generated}

    def update_user(self, who, new_name=None, new_username=None, new_password=None, reset_password=False) -> dict:
        changes, result = [], {}
        with get_conn() as conn:
            t = self._target(conn, who)
            if t["id"] != self.user.id:
                self._need("users.edit", "You don't have permission to edit users.")
                self._check_grantable(t["permissions"], f"manage {t['display_name']}")
            sets, params = [], []
            if new_name:
                name = self._clean_name(new_name)
                if name != t["display_name"]:
                    if self._name_taken(conn, name, t["id"]):
                        raise Conflict(f"A user named '{name}' already exists.")
                    sets.append("display_name=?"); params.append(name); changes.append(f"name '{t['display_name']}' -> '{name}'")
            if new_username:
                uname = self._clean_username(new_username)
                if uname != t["username"]:
                    if self._username_taken(conn, uname, t["id"]):
                        raise Conflict(f"Username '{uname}' is already taken.")
                    sets.append("username=?"); params.append(uname); changes.append(f"username '{t['username']}' -> '{uname}'")
            if new_password or reset_password:
                pwd = self._check_password(str(new_password)) if new_password else generate_password()
                pw_hash, salt = hash_password(pwd)
                sets += ["password_hash=?", "salt=?"]; params += [pw_hash, salt]
                changes.append("password reset")
                result["password"], result["password_generated"] = pwd, not new_password
            if not sets:
                raise BadRequest("Nothing to update - provide a new name, username or password.")
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", params + [t["id"]])
            if ("password" in result or new_username) and t["id"] != self.user.id:
                revoke_all_tokens(conn, t["id"])
            new = conn.execute("SELECT id, username, display_name FROM users WHERE id=?", (t["id"],)).fetchone()
        if any(c.startswith("name") for c in changes) and new["id"] != self.user.id:
            notify(new["id"], None, "profile_changed", f"Your display name was changed to '{new['display_name']}'.")
        audit(self.user.id, "user_update", f"{t['display_name']}: {'; '.join(changes)}")
        return {"id": new["id"], "username": new["username"], "display_name": new["display_name"], "changes": changes, **result}

    # ---- pending tasks (role change / delete) ------------------------------------------------
    def _pending_plan(self, conn, t, losing_work: bool, reassign_to, delete_tasks, verb) -> dict:
        pending = completed = 0
        target = None
        if losing_work:
            pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status != ?", (t["id"], STATUS_COMPLETED)).fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status = ?", (t["id"], STATUS_COMPLETED)).fetchone()[0]
        if reassign_to and delete_tasks:
            raise BadRequest("Choose either 'reassign pending tasks' or 'delete pending tasks', not both.")
        if reassign_to and pending:
            target = resolve_user(conn, reassign_to, assignable_only=True)
            if target["id"] == t["id"]:
                raise BadRequest(f"Cannot reassign tasks to the user you want to {verb}.")
        if pending and not target and not delete_tasks:
            raise BadRequest(f"{t['display_name']} has {pending} pending task(s). Choose someone to reassign them to, "
                             f"or choose to delete those tasks.")
        if pending and delete_tasks and not self.user.has("tasks.delete"):
            raise Forbidden("You don't have permission to delete tasks - reassign them instead.")
        if pending and target and not self.user.has("tasks.edit"):
            raise Forbidden("You don't have permission to reassign tasks.")
        text = ("no pending tasks" if not pending else f"{pending} pending task(s) will be reassigned to {target['display_name']}"
                if target else f"{pending} pending task(s) will be permanently deleted")
        return {"pending": pending, "completed": completed, "target": target, "delete": bool(delete_tasks and pending), "text": text}

    def _apply_pending(self, user_id: int, plan: dict) -> list:
        if not plan["pending"]:
            return []
        with get_conn() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM tasks WHERE assigned_to=? AND status != ?", (user_id, STATUS_COMPLETED))]
        repo = TaskRepository(self.user)
        for tid in ids:
            if plan["target"]:
                repo.update_task(tid, {"assigned_to": plan["target"]["username"]})
            else:
                repo.delete_task(tid)
        return ids

    # ---- change role ------------------------------------------------------------------------
    def role_preview(self, who, new_role, reassign_to=None, delete_tasks=False) -> dict:
        self._need("roles.manage", "You don't have permission to change roles.")
        with get_conn() as conn:
            t = self._target(conn, who)
            self._not_self(t, "change the role of")
            r = resolve_role(conn, new_role)
            if r["id"] == t["role_id"]:
                raise BadRequest(f"{t['display_name']} already has the role '{r['name']}'.")
            self._check_grantable(t["permissions"], f"manage {t['display_name']}")
            self._check_grantable(r["permissions"], f"give the role '{r['name']}'")
            if "roles.manage" in t["permissions"] and "roles.manage" not in r["permissions"]:
                self._keeps_a_role_manager(conn, t["id"])
            losing = "tasks.update_own" in t["permissions"] and "tasks.update_own" not in r["permissions"]
            plan = self._pending_plan(conn, t, losing, reassign_to, delete_tasks, "change")
        summary = (f"Change {t['display_name']} ({t['username']}) from '{t['role_name']}' to '{r['name']}'"
                   + (f" - {plan['text']}" if losing else "") + ". They will be signed out and must log in again.")
        return {"user_id": t["id"], "name": t["display_name"], "username": t["username"], "from_role": t["role_name"],
                "to_role": r["name"], "to_role_id": r["id"], "plan": plan, "summary": summary,
                "pending": plan["pending"], "completed": plan["completed"]}

    def change_role(self, who, new_role, reassign_to=None, delete_tasks=False) -> dict:
        p = self.role_preview(who, new_role, reassign_to, delete_tasks)
        ids = self._apply_pending(p["user_id"], p["plan"])
        with get_conn() as conn:
            conn.execute("UPDATE users SET role_id=? WHERE id=?", (p["to_role_id"], p["user_id"]))
            self._end_sessions(conn, p["user_id"])
            conn.execute("DELETE FROM notifications WHERE user_id=?", (p["user_id"],))
        notify(p["user_id"], None, "role_changed", f"Your role was changed to '{p['to_role']}' by {self.user.display_name}.")
        audit(self.user.id, "user_role_change", p["summary"])
        return {**{k: v for k, v in p.items() if k != "plan"}, "affected_task_ids": ids}

    # ---- delete ----------------------------------------------------------------------------
    def delete_preview(self, who, reassign_to=None, delete_tasks=False) -> dict:
        self._need("users.delete", "You don't have permission to delete users.")
        with get_conn() as conn:
            t = self._target(conn, who)
            self._not_self(t, "delete")
            self._check_grantable(t["permissions"], f"delete {t['display_name']}")
            if "roles.manage" in t["permissions"]:
                self._keeps_a_role_manager(conn, t["id"])
            plan = self._pending_plan(conn, t, "tasks.update_own" in t["permissions"], reassign_to, delete_tasks, "delete")
        summary = (f"Delete {t['display_name']} ({t['username']}, role '{t['role_name']}')"
                   + (f" - {plan['text']}." if plan["pending"] else ".")
                   + (f" {plan['completed']} completed task(s) are kept for reports." if plan["completed"] else ""))
        return {"user_id": t["id"], "name": t["display_name"], "username": t["username"], "role": t["role_name"],
                "plan": plan, "summary": summary, "pending": plan["pending"], "completed": plan["completed"]}

    def delete_user(self, who, reassign_to=None, delete_tasks=False) -> dict:
        p = self.delete_preview(who, reassign_to, delete_tasks)
        ids = self._apply_pending(p["user_id"], p["plan"])
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_active=0, username=?, display_name=? WHERE id=?",
                         (f"{p['username']}__removed_{p['user_id']}"[:60], f"{p['name']} (removed)", p["user_id"]))
            self._end_sessions(conn, p["user_id"])
            conn.execute("DELETE FROM notifications WHERE user_id=?", (p["user_id"],))
        audit(self.user.id, "user_delete", p["summary"])
        return {**{k: v for k, v in p.items() if k != "plan"}, "affected_task_ids": ids}
