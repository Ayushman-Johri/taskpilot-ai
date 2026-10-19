"""Tools for the ADMIN "act" mode (only used when the admin asks for a change).
The tool list is STATIC (same order every call) so Groq can cache it as part of the prompt prefix.
Read questions never send tools - they get a compact data snapshot instead (see context.py).

Safety: create/update run immediately; delete_task, delete_user and change_role only create a
pending action that the admin must CONFIRM. Passwords never go to the LLM."""
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from auth import User
from config import STATUSES, PRIORITIES, AI_ACTION_EXPIRY_MIN
from database import audit, get_conn
from errors import AppError, BadRequest
from repository import TaskRepository
from users import UserRepository
from utils import now_utc, to_iso, parse_dt, fmt_short

S, I, B, N = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "number"}
ST = {"type": "string", "enum": STATUSES}
PR = {"type": "string", "enum": list(PRIORITIES)}
RO = {"type": "string", "enum": ["agent", "admin"]}
CONFIRM_TOOLS = {"delete_task", "delete_user", "change_role"}

WRITE_INTENT_RE = re.compile(
    r"\b(assign|reassign|create|add|make|delete|remove|rename|change|update|set|mark|extend|postpone|"
    r"move|shift|promote|demote|reset|edit|hand\s*over|close|reopen|"
    r"bana|banao|karo|kar\s+do|de\s+do|hatao|hata|badlo|badal|daalo|dalo)\b|\bgive\b(?!\s+(me|us)\b)", re.I)
READ_ONLY_START = re.compile(r"^\s*(which|what|who|how|show|list|tell|kya|kaun|kitne|kab|does|is|are|can\s+you\s+(show|tell|list))\b", re.I)


@dataclass
class ToolContext:
    actions: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    changed: bool = False


def _fn(name, desc, props=None, req=None):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": req or []}}}


ADMIN_TOOLS = [
    _fn("get_tasks", "Find tasks.", {"search": S, "agent": S, "status": ST, "pending_only": B}),
    _fn("create_task", "Create+assign task.", {"title": S, "assigned_to": S, "deadline": S, "priority": PR,
                                               "description": S, "estimated_hours": N}, ["title", "assigned_to", "deadline"]),
    _fn("update_task", "Change task; only changed fields. assigned_to=reassign.",
        {"task_id": I, "title": S, "description": S, "assigned_to": S, "priority": PR, "deadline": S,
         "status": ST, "progress": I, "estimated_hours": N}, ["task_id"]),
    _fn("delete_task", "Delete task (confirm card).", {"task_id": I}, ["task_id"]),
    _fn("create_user", "Add user.", {"name": S, "role": RO}, ["name"]),
    _fn("update_user", "Rename/username/reset password.", {"user": S, "new_name": S, "new_username": S,
                                                           "reset_password": B}, ["user"]),
    _fn("change_role", "Promote/demote (confirm card).", {"user": S, "role": RO, "reassign_to": S, "delete_tasks": B},
        ["user", "role"]),
    _fn("delete_user", "Delete user (confirm card).", {"user": S, "reassign_to": S, "delete_tasks": B}, ["user"]),
]
ADMIN_TOOL_NAMES = {t["function"]["name"] for t in ADMIN_TOOLS}


def row_line(t: dict) -> str:
    return (f"{t['id']}|{t['title']}|{t['agent_name']}|{t['status']}|{t['progress']}|{t['priority']}|"
            f"{fmt_short(t['deadline'])}|{t['remaining_human']}")


# ---------------------------------------------------------------------------
# Pending (confirm-first) actions
# ---------------------------------------------------------------------------
def _preview(user: User, tool: str, args: dict) -> str:
    if tool == "delete_task":
        t = TaskRepository(user).get_task(args.get("task_id"))
        return f"Delete task #{t['id']} '{t['title']}' (assigned to {t['agent_name']}, status {t['status']})."
    repo = UserRepository(user)
    if tool == "delete_user":
        return repo.delete_preview(args.get("user"), args.get("reassign_to"), bool(args.get("delete_tasks")))["summary"]
    return repo.role_preview(args.get("user"), args.get("role"), args.get("reassign_to"),
                             bool(args.get("delete_tasks")))["summary"]


def create_pending_action(user: User, tool: str, args: dict) -> dict:
    summary = _preview(user, tool, args)
    args_json = json.dumps(args, sort_keys=True)
    with get_conn() as conn:
        existing = conn.execute("SELECT id, created_at FROM ai_actions WHERE user_id=? AND tool=? AND args=? "
                                "AND status='pending' ORDER BY created_at DESC LIMIT 1", (user.id, tool, args_json)).fetchone()
        if existing and parse_dt(existing["created_at"]) > now_utc() - timedelta(minutes=AI_ACTION_EXPIRY_MIN):
            action_id = existing["id"]
        else:
            action_id = secrets.token_urlsafe(9)
            conn.execute("INSERT INTO ai_actions(id, user_id, tool, args, summary, created_at) VALUES (?,?,?,?,?,?)",
                         (action_id, user.id, tool, args_json, summary, to_iso(now_utc())))
    return {"id": action_id, "tool": tool, "summary": summary, "status": "pending"}


def expire_old_actions(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE ai_actions SET status='expired', result='This request expired. Ask the assistant again.', "
                     "resolved_at=? WHERE user_id=? AND status='pending' AND created_at < ?",
                     (to_iso(now_utc()), user_id, to_iso(now_utc() - timedelta(minutes=AI_ACTION_EXPIRY_MIN))))


def get_actions(user: User, ids: list) -> list:
    if not ids:
        return []
    expire_old_actions(user.id)
    with get_conn() as conn:
        rows = conn.execute(f"SELECT id, tool, summary, status, result FROM ai_actions WHERE user_id=? "
                            f"AND id IN ({','.join('?' * len(ids))})", [user.id, *ids]).fetchall()
    by_id = {r["id"]: dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def resolve_action(user: User, action_id: str, confirm: bool) -> dict:
    if not user.is_admin:
        raise BadRequest("Only Admins can confirm actions.")
    expire_old_actions(user.id)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_actions WHERE id=? AND user_id=?", (action_id, user.id)).fetchone()
    if not row:
        raise BadRequest("Action not found.")
    if row["status"] != "pending":
        return {"id": row["id"], "summary": row["summary"], "status": row["status"], "result": row["result"]}
    status, result = "cancelled", "Cancelled - nothing was changed."
    if confirm:
        args = json.loads(row["args"])
        try:
            if row["tool"] == "delete_task":
                t = TaskRepository(user).delete_task(args["task_id"])
                result = f"Task #{t['id']} '{t['title']}' was deleted."
            else:
                repo = UserRepository(user)
                if row["tool"] == "delete_user":
                    r = repo.delete_user(args["user"], args.get("reassign_to"), bool(args.get("delete_tasks")))
                    head = f"{r['name']} was deleted."
                else:
                    r = repo.change_role(args["user"], args["role"], args.get("reassign_to"), bool(args.get("delete_tasks")))
                    head = f"{r['name']} is now an {r['to_role']}."
                extra = ""
                if r.get("pending"):
                    extra = (f" {r['pending']} pending task(s) reassigned." if args.get("reassign_to")
                             else f" {r['pending']} pending task(s) deleted.")
                result = head + extra
            status = "done"
        except AppError as e:
            status, result = "failed", e.message
    with get_conn() as conn:
        conn.execute("UPDATE ai_actions SET status=?, result=?, resolved_at=? WHERE id=?",
                     (status, result, to_iso(now_utc()), row["id"]))
    audit(user.id, f"ai_action_{status}", f"{row['summary']} -> {result}")
    return {"id": row["id"], "summary": row["summary"], "status": status, "result": result}


# ---------------------------------------------------------------------------
# Executor (results are short text lines, not JSON -> fewer tokens)
# ---------------------------------------------------------------------------
def _execute(user: User, name: str, args: dict, ctx: ToolContext) -> str:
    repo = TaskRepository(user)
    if name == "get_tasks":
        tasks = repo.list_tasks(agent=args.get("agent"), status=args.get("status"),
                                search=(args.get("search") or "").strip() or None, pending_only=bool(args.get("pending_only")))
        return f"{len(tasks)} found\n" + "\n".join(row_line(t) for t in tasks[:25])
    audit(user.id, "ai_tool", f"{name} {json.dumps(args)[:500]}")
    if name in CONFIRM_TOOLS:
        action = create_pending_action(user, name, args)
        ctx.actions.append(action)
        return f"AWAITING_CONFIRMATION: {action['summary']} Nothing changed yet; admin must press Confirm."
    if name == "create_task":
        t = repo.create_task(args)
        ctx.changed = True
        return "CREATED " + row_line(t)
    if name == "update_task":
        fields = {k: args[k] for k in ("title", "description", "assigned_to", "priority", "deadline", "status",
                                        "progress", "estimated_hours") if args.get(k) is not None}
        if not fields:
            return "ERROR: no fields to update"
        t = repo.admin_update_task(args.get("task_id"), fields)
        ctx.changed = True
        return f"UPDATED ({'; '.join(t.get('changes') or ['no change'])}) " + row_line(t)
    if name == "create_user":
        u = UserRepository(user).create_user(args.get("name"), args.get("role") or "agent")
        ctx.changed = True
        ctx.notices.append({"type": "credentials", "title": f"New {u['role']}: {u['display_name']}",
                            "username": u["username"], "password": u["password"]})
        return f"CREATED {u['role']} {u['display_name']} username={u['username']} (password shown in secure card)"
    if name == "update_user":
        u = UserRepository(user).update_user(args.get("user"), args.get("new_name"), args.get("new_username"),
                                             None, bool(args.get("reset_password")))
        ctx.changed = True
        if u.get("password"):
            ctx.notices.append({"type": "credentials", "title": f"Password reset: {u['display_name']}",
                                "username": u["username"], "password": u["password"]})
        return f"UPDATED {u['display_name']}: {'; '.join(u['changes'])}"
    return f"ERROR: unknown tool {name}"


def execute_tool(user: User, name: str, raw_args, ctx: ToolContext) -> str:
    if not user.is_admin or name not in ADMIN_TOOL_NAMES:
        audit(user.id, "ai_access_denied", f"tool {name} not allowed for {user.role}")
        return "ERROR: NOT_AUTHORIZED"
    try:
        args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else (raw_args or {})
        args = args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        return "ERROR: arguments were not valid JSON"
    try:
        return _execute(user, name, args, ctx)
    except AppError as e:
        return f"ERROR: {e.message}"
    except (TypeError, ValueError, KeyError) as e:
        return f"ERROR: invalid arguments ({e})"
