"""User management (agents AND admins) - ADMIN ONLY.
Add user (agent/admin), rename / change username / reset password, promote / demote, delete.
Safety: no self role-change or self-delete; at least one active admin must remain; any role change,
delete or password reset logs the user out everywhere (JWT token_version bump)."""
import re
from typing import Optional

from auth import User, hash_password, revoke_all_tokens
from config import MIN_PASSWORD_LEN, STATUS_COMPLETED, ROLES
from database import get_conn, audit
from errors import BadRequest, Conflict, Forbidden
from notifications import notify
from repository import resolve_user, TaskRepository, counts
from utils import generate_password, slugify_username

NAME_RE = re.compile(r"^[\w][\w .'\-]{1,49}$", re.UNICODE)
USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.]{2,29}$")


class UserRepository:
    def __init__(self, user: User):
        if not user.is_admin:
            raise Forbidden("Only Admins can manage users.")
        self.user = user

    # ---- validation helpers ----------------------------------------------------
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
    def _check_role(role) -> str:
        role = str(role or "agent").strip().lower()
        if role not in ROLES:
            raise BadRequest("Role must be 'agent' or 'admin'.")
        return role

    @staticmethod
    def _name_taken(conn, name, exclude_id=None) -> bool:
        return conn.execute("SELECT 1 FROM users WHERE is_active=1 AND lower(display_name)=lower(?) AND id IS NOT ?",
                            (name, exclude_id)).fetchone() is not None

    @staticmethod
    def _username_taken(conn, username, exclude_id=None) -> bool:
        return conn.execute("SELECT 1 FROM users WHERE lower(username)=? AND id IS NOT ?",
                            (username, exclude_id)).fetchone() is not None

    def _unique_username(self, conn, base: str) -> str:
        if not USERNAME_RE.match(base):
            base = f"user_{base}".strip("_")[:30]
        if not USERNAME_RE.match(base):
            base = "user"
        candidate, i = base, 2
        while self._username_taken(conn, candidate):
            candidate = f"{base[:27]}{i}"
            i += 1
        return candidate

    def _not_self(self, row, action: str):
        if row["id"] == self.user.id:
            raise Forbidden(f"You cannot {action} your own account.")

    @staticmethod
    def _admin_count(conn) -> int:
        return conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]

    @staticmethod
    def _end_user_sessions(conn, user_id: int) -> None:
        revoke_all_tokens(conn, user_id)
        conn.execute("DELETE FROM chat_messages WHERE user_id=?", (user_id,))
        conn.execute("UPDATE ai_actions SET status='cancelled', result='User changed.' WHERE user_id=? AND status='pending'",
                     (user_id,))

    # ---- reads ------------------------------------------------------------------
    def list_agents(self) -> list:
        tasks = TaskRepository(self.user).list_tasks()
        with get_conn() as conn:
            rows = conn.execute("SELECT id, username, display_name FROM users WHERE role='agent' AND is_active=1 "
                                "ORDER BY display_name").fetchall()
        return [{"id": r["id"], "username": r["username"], "display_name": r["display_name"], "role": "agent",
                 **counts([t for t in tasks if t["assigned_to"] == r["id"]])} for r in rows]

    def list_admins(self) -> list:
        with get_conn() as conn:
            rows = conn.execute("SELECT id, username, display_name FROM users WHERE role='admin' AND is_active=1 "
                                "ORDER BY display_name").fetchall()
        return [{"id": r["id"], "username": r["username"], "display_name": r["display_name"], "role": "admin",
                 "is_you": r["id"] == self.user.id} for r in rows]

    # ---- create / update ----------------------------------------------------------
    def create_user(self, name, role="agent", username=None, password=None) -> dict:
        name, role = self._clean_name(name), self._check_role(role)
        generated = not password
        password = generate_password() if generated else self._check_password(str(password))
        with get_conn() as conn:
            if self._name_taken(conn, name):
                raise Conflict(f"A user named '{name}' already exists.")
            if username:
                username = self._clean_username(username)
                if self._username_taken(conn, username):
                    raise Conflict(f"Username '{username}' is already taken.")
            else:
                username = self._unique_username(conn, slugify_username(name))
            pw_hash, salt = hash_password(password)
            new_id = conn.execute("INSERT INTO users(username, display_name, role, password_hash, salt) VALUES (?,?,?,?,?)",
                                  (username, name, role, pw_hash, salt)).lastrowid
        audit(self.user.id, f"{role}_create", f"{name} ({username})")
        return {"id": new_id, "username": username, "display_name": name, "role": role,
                "password": password, "password_generated": generated}

    def update_user(self, who, new_name=None, new_username=None, new_password=None, reset_password=False) -> dict:
        changes, result = [], {}
        with get_conn() as conn:
            row = resolve_user(conn, who, None)
            sets, params = [], []
            if new_name:
                name = self._clean_name(new_name)
                if name != row["display_name"]:
                    if self._name_taken(conn, name, row["id"]):
                        raise Conflict(f"A user named '{name}' already exists.")
                    sets.append("display_name=?"); params.append(name)
                    changes.append(f"name '{row['display_name']}' -> '{name}'")
            if new_username:
                uname = self._clean_username(new_username)
                if uname != row["username"]:
                    if self._username_taken(conn, uname, row["id"]):
                        raise Conflict(f"Username '{uname}' is already taken.")
                    sets.append("username=?"); params.append(uname)
                    changes.append(f"username '{row['username']}' -> '{uname}'")
            if new_password or reset_password:
                pwd = self._check_password(str(new_password)) if new_password else generate_password()
                pw_hash, salt = hash_password(pwd)
                sets += ["password_hash=?", "salt=?"]; params += [pw_hash, salt]
                changes.append("password reset")
                result["password"] = pwd
                result["password_generated"] = not new_password
            if not sets:
                raise BadRequest("Nothing to update - provide a new name, username or password.")
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", params + [row["id"]])
            if ("password" in result or new_username) and row["id"] != self.user.id:
                revoke_all_tokens(conn, row["id"])
            new = conn.execute("SELECT id, username, display_name, role FROM users WHERE id=?", (row["id"],)).fetchone()
        if any(c.startswith("name") for c in changes):
            notify(new["id"], None, "profile_changed", f"Admin changed your display name to '{new['display_name']}'.")
        audit(self.user.id, "user_update", f"{row['display_name']}: {'; '.join(changes)}")
        return {"id": new["id"], "username": new["username"], "display_name": new["display_name"],
                "role": new["role"], "changes": changes, **result}

    # ---- pending-task handling (delete and promote) ------------------------------------
    def _pending_plan(self, conn, row, reassign_to, delete_tasks, verb) -> dict:
        pending = completed = 0
        target = None
        if row["role"] == "agent":
            pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status != ?",
                                   (row["id"], STATUS_COMPLETED)).fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE assigned_to=? AND status = ?",
                                     (row["id"], STATUS_COMPLETED)).fetchone()[0]
        if reassign_to and delete_tasks:
            raise BadRequest("Choose either 'reassign pending tasks' or 'delete pending tasks', not both.")
        if reassign_to and pending:
            target = resolve_user(conn, reassign_to, "agent")
            if target["id"] == row["id"]:
                raise BadRequest(f"Cannot reassign tasks to the agent you want to {verb}.")
        if pending and not target and not delete_tasks:
            raise BadRequest(f"{row['display_name']} has {pending} pending task(s). Choose an agent to reassign "
                             f"them to, or choose to delete those tasks.")
        text = ("no pending tasks" if not pending else
                f"{pending} pending task(s) will be reassigned to {target['display_name']}" if target else
                f"{pending} pending task(s) will be permanently deleted")
        return {"pending": pending, "completed": completed, "target": target,
                "delete": bool(delete_tasks and pending), "text": text}

    def _apply_pending(self, user_id: int, plan: dict) -> list:
        repo = TaskRepository(self.user)
        ids = [t["id"] for t in repo.list_tasks(pending_only=True) if t["assigned_to"] == user_id]
        for tid in ids:
            if plan["target"]:
                repo.admin_update_task(tid, {"assigned_to": plan["target"]["username"]})
            else:
                repo.delete_task(tid)
        return ids

    # ---- change role ----------------------------------------------------------------
    def role_preview(self, who, new_role, reassign_to=None, delete_tasks=False) -> dict:
        new_role = self._check_role(new_role)
        with get_conn() as conn:
            row = resolve_user(conn, who, None)
            self._not_self(row, "change the role of")
            if row["role"] == new_role:
                raise BadRequest(f"{row['display_name']} is already an {new_role}.")
            if row["role"] == "admin" and self._admin_count(conn) <= 1:
                raise BadRequest("At least one admin must remain.")
            plan = self._pending_plan(conn, row, reassign_to, delete_tasks, "promote")
        what = "Promote" if new_role == "admin" else "Change"
        summary = (f"{what} {row['display_name']} ({row['username']}) from {row['role']} to {new_role}"
                   + (f" - {plan['text']}" if row["role"] == "agent" else "")
                   + ". They will be logged out and must sign in again.")
        return {"user_id": row["id"], "name": row["display_name"], "username": row["username"],
                "from_role": row["role"], "to_role": new_role, "plan": plan, "summary": summary,
                "pending": plan["pending"], "completed": plan["completed"]}

    def change_role(self, who, new_role, reassign_to=None, delete_tasks=False) -> dict:
        p = self.role_preview(who, new_role, reassign_to, delete_tasks)
        ids = self._apply_pending(p["user_id"], p["plan"]) if p["from_role"] == "agent" else []
        with get_conn() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (p["to_role"], p["user_id"]))
            self._end_user_sessions(conn, p["user_id"])
            conn.execute("DELETE FROM notifications WHERE user_id=?", (p["user_id"],))
        notify(p["user_id"], None, "role_changed", f"Your role was changed to {p['to_role']} by {self.user.display_name}.")
        audit(self.user.id, "user_role_change", p["summary"])
        return {**{k: v for k, v in p.items() if k != "plan"}, "affected_task_ids": ids}

    # ---- delete -------------------------------------------------------------------
    def delete_preview(self, who, reassign_to=None, delete_tasks=False) -> dict:
        with get_conn() as conn:
            row = resolve_user(conn, who, None)
            self._not_self(row, "delete")
            if row["role"] == "admin" and self._admin_count(conn) <= 1:
                raise BadRequest("At least one admin must remain.")
            plan = self._pending_plan(conn, row, reassign_to, delete_tasks, "delete")
        summary = (f"Delete {row['role']} {row['display_name']} ({row['username']})"
                   + (f" - {plan['text']}." if row["role"] == "agent" else ".")
                   + (f" {plan['completed']} completed task(s) are kept for reports." if plan["completed"] else ""))
        return {"user_id": row["id"], "name": row["display_name"], "username": row["username"], "role": row["role"],
                "plan": plan, "summary": summary, "pending": plan["pending"], "completed": plan["completed"],
                "reassign_to": plan["target"]["display_name"] if plan["target"] else None, "delete_tasks": plan["delete"]}

    def delete_user(self, who, reassign_to=None, delete_tasks=False) -> dict:
        p = self.delete_preview(who, reassign_to, delete_tasks)
        ids = self._apply_pending(p["user_id"], p["plan"]) if p["role"] == "agent" else []
        with get_conn() as conn:
            conn.execute("UPDATE users SET is_active=0, username=?, display_name=? WHERE id=?",
                         (f"{p['username']}__removed_{p['user_id']}"[:60], f"{p['name']} (removed)", p["user_id"]))
            self._end_user_sessions(conn, p["user_id"])
            conn.execute("DELETE FROM notifications WHERE user_id=?", (p["user_id"],))
        audit(self.user.id, "user_delete", p["summary"])
        return {**{k: v for k, v in p.items() if k != "plan"}, "affected_task_ids": ids}
