"""Tools for the AI "act" mode. The tool list is built from the user's PERMISSIONS:
a tool is only offered if the role has the matching permission, and every tool still runs through
the repositories, which check the permission again (defence in depth).

Fixed tool order -> identical tool list for identical permission sets -> Groq prefix caching.
delete_task, delete_user and change_role only create a pending card that must be CONFIRMED."""
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from auth import User
from config import STATUSES, PRIORITIES, AI_ACTION_EXPIRY_MIN, STATUS_COMPLETED
from database import audit, get_conn
from errors import AppError, BadRequest
from repository import TaskRepository
from roles import RoleRepository
from users import UserRepository
from utils import now_utc, to_iso, parse_dt, fmt_short
from .audit_view import read_audit

S, I, B, N = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "number"}
ST = {"type": "string", "enum": STATUSES}
PR = {"type": "string", "enum": list(PRIORITIES)}
CONFIRM_TOOLS = {"delete_task", "delete_user", "change_role"}

WRITE_INTENT_RE = re.compile(
    r"\b(assign|reassign|create|add|make|delete|remove|rename|change|update|set|mark|extend|postpone|"
    r"move|shift|promote|demote|reset|edit|hand\s*over|close|reopen|start|finish|complete|"
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


# (tool, any-of permissions)
TOOL_SPECS = [
    (_fn("get_tasks", "Find tasks you can see.", {"search": S, "assignee": S, "status": ST, "pending_only": B}),
     ("tasks.view_all", "tasks.view_own")),
    (_fn("update_my_progress", "Update status/progress/note of a task assigned to ME. Give task_id or search.",
         {"task_id": I, "search": S, "status": ST, "progress": I, "note": S}), ("tasks.update_own",)),
    (_fn("create_task", "Create+assign task.", {"title": S, "assigned_to": S, "deadline": S, "priority": PR,
                                               "description": S, "estimated_hours": N}, ["title", "assigned_to", "deadline"]), ("tasks.create",)),
    (_fn("update_task", "Edit task details or reassign. Cannot change status/progress.",
         {"task_id": I, "title": S, "description": S, "assigned_to": S, "priority": PR, "deadline": S, "estimated_hours": N},
         ["task_id"]), ("tasks.edit",)),
    (_fn("delete_task", "Delete task (confirm card).", {"task_id": I}, ["task_id"]), ("tasks.delete",)),
    (_fn("list_roles", "List roles."), ("users.create", "roles.manage")),
    (_fn("create_user", "Add user with a role name (default Agent).", {"name": S, "role": S}, ["name"]), ("users.create",)),
    (_fn("update_user", "Rename/username/reset password.", {"user": S, "new_name": S, "new_username": S, "reset_password": B}, ["user"]),
     ("users.edit",)),
    (_fn("change_role", "Change a user's role (confirm card).", {"user": S, "role": S, "reassign_to": S, "delete_tasks": B},
         ["user", "role"]), ("roles.manage",)),
    (_fn("delete_user", "Delete user (confirm card).", {"user": S, "reassign_to": S, "delete_tasks": B}, ["user"]), ("users.delete",)),
    (_fn("get_audit_log", "Read audit log entries.", {"task_id": I, "user": S, "action": S, "limit": I}), ("audit.view",)),
]


def tools_for(user: User) -> list:
    return [spec for spec, perms in TOOL_SPECS if user.has_any(*perms)]


def allowed_tool_names(user: User) -> set:
    return {t["function"]["name"] for t in tools_for(user)}


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
    return repo.role_preview(args.get("user"), args.get("role"), args.get("reassign_to"), bool(args.get("delete_tasks")))["summary"]


def create_pending_action(user: User, tool: str, args: dict) -> dict:
    summary = _preview(user, tool, args)
    args_json = json.dumps(args, sort_keys=True)
    with get_conn() as conn:
        existing = conn.execute("SELECT id, created_at FROM ai_actions WHERE user_id=? AND tool=? AND args=? AND status='pending' "
                                "ORDER BY created_at DESC LIMIT 1", (user.id, tool, args_json)).fetchone()
        if existing and parse_dt(existing["created_at"]) > now_utc() - timedelta(minutes=AI_ACTION_EXPIRY_MIN):
            action_id = existing["id"]
        else:
            action_id = secrets.token_urlsafe(9)
            conn.execute("INSERT INTO ai_actions(id, user_id, tool, args, summary, created_at) VALUES (?,?,?,?,?,?)",
                         (action_id, user.id, tool, args_json, summary, to_iso(now_utc())))
    return {"id": action_id, "tool": tool, "summary": summary, "status": "pending"}


def expire_old_actions(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE ai_actions SET status='expired', result='This request expired. Ask the assistant again.', resolved_at=? "
                     "WHERE user_id=? AND status='pending' AND created_at < ?",
                     (to_iso(now_utc()), user_id, to_iso(now_utc() - timedelta(minutes=AI_ACTION_EXPIRY_MIN))))


def get_actions(user: User, ids: list) -> list:
    if not ids:
        return []
    expire_old_actions(user.id)
    with get_conn() as conn:
        rows = conn.execute(f"SELECT id, tool, summary, status, result FROM ai_actions WHERE user_id=? AND id IN ({','.join('?' * len(ids))})",
                            [user.id, *ids]).fetchall()
    by_id = {r["id"]: dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def resolve_action(user: User, action_id: str, confirm: bool) -> dict:
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
        try:   # permissions are re-checked NOW by the repositories (role may have changed since the card was created)
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
                    head = f"{r['name']} now has the role '{r['to_role']}'."
                extra = ""
                if r.get("pending"):
                    extra = f" {r['pending']} pending task(s) " + ("reassigned." if args.get("reassign_to") else "deleted.")
                result = head + extra
            status = "done"
        except AppError as e:
            status, result = "failed", e.message
    with get_conn() as conn:
        conn.execute("UPDATE ai_actions SET status=?, result=?, resolved_at=? WHERE id=?", (status, result, to_iso(now_utc()), row["id"]))
    audit(user.id, f"ai_action_{status}", f"{row['summary']} -> {result}")
    return {"id": row["id"], "summary": row["summary"], "status": status, "result": result}


# ---------------------------------------------------------------------------
# Executor (short text results -> fewer tokens, and explicit UPDATED / NO CHANGE / ERROR words)
# ---------------------------------------------------------------------------
def _find_my_task(repo: TaskRepository, args: dict):
    if args.get("task_id"):
        return repo.get_task(args["task_id"])["id"], None
    search = (args.get("search") or "").strip()
    if not search:
        return None, "ERROR: say which task (task id or part of the title)."
    found = [t for t in repo.list_tasks(search=search, mine=True) if t["status"] != STATUS_COMPLETED] \
        or repo.list_tasks(search=search, mine=True)
    if not found:
        return None, f"ERROR: none of your tasks match '{search}'."
    if len(found) > 1:
        return None, "MULTIPLE MATCHES - ask which one:\n" + "\n".join(row_line(t) for t in found[:10])
    return found[0]["id"], None


def _execute(user: User, name: str, args: dict, ctx: ToolContext) -> str:
    repo = TaskRepository(user)
    if name == "get_tasks":
        tasks = repo.list_tasks(agent=args.get("assignee") if user.sees_all_tasks else None, status=args.get("status"),
                                search=(args.get("search") or "").strip() or None, pending_only=bool(args.get("pending_only")))
        return f"{len(tasks)} found\n" + "\n".join(row_line(t) for t in tasks[:25])
    if name == "list_roles":
        return "\n".join(f"{r['name']}: {', '.join(r['permissions'])}" for r in RoleRepository(user).list_roles())
    if name == "get_audit_log":
        rows = read_audit(user, args.get("task_id"), args.get("user"), args.get("action"), args.get("limit") or 20)
        return f"{len(rows)} entries\n" + "\n".join(f"{r['when']}|{r['who']}|{r['action']}|{r['detail']}" for r in rows)

    audit(user.id, "ai_tool", f"{name} {json.dumps(args)[:500]}")
    if name in CONFIRM_TOOLS:
        action = create_pending_action(user, name, args)
        ctx.actions.append(action)
        return f"AWAITING_CONFIRMATION: {action['summary']} Nothing changed yet; the user must press Confirm."
    if name == "update_my_progress":
        task_id, problem = _find_my_task(repo, args)
        if problem:
            return problem
        try:
            t = repo.update_progress(task_id, {"status": args.get("status"), "progress": args.get("progress"), "note": args.get("note")})
        except BadRequest as e:
            if e.message.startswith("Nothing changed"):
                return f"NO CHANGE: {e.message}"
            raise
        ctx.changed = True
        prev = t["previous"]
        return f"UPDATED #{t['id']} '{t['title']}': {prev['status']} {prev['progress']}% -> {t['status']} {t['progress']}%"
    if name == "create_task":
        t = repo.create_task(args)
        ctx.changed = True
        return "CREATED " + row_line(t)
    if name == "update_task":
        fields = {k: args[k] for k in ("title", "description", "assigned_to", "priority", "deadline", "estimated_hours")
                  if args.get(k) is not None}
        if not fields:
            return "ERROR: no editable fields given. Status/progress can only be changed by the assignee."
        t = repo.update_task(args.get("task_id"), fields)
        if not t.get("changes"):
            return "NO CHANGE: values were already the same. " + row_line(t)
        ctx.changed = True
        return f"UPDATED ({'; '.join(t['changes'])}) " + row_line(t)
    if name == "create_user":
        u = UserRepository(user).create_user(args.get("name"), args.get("role") or "Agent")
        ctx.changed = True
        ctx.notices.append({"type": "credentials", "title": f"New user: {u['display_name']} ({u['role']})",
                            "username": u["username"], "password": u["password"]})
        return f"CREATED {u['display_name']} role={u['role']} username={u['username']} (password shown in secure card)"
    if name == "update_user":
        u = UserRepository(user).update_user(args.get("user"), args.get("new_name"), args.get("new_username"), None,
                                             bool(args.get("reset_password")))
        ctx.changed = True
        if u.get("password"):
            ctx.notices.append({"type": "credentials", "title": f"Password reset: {u['display_name']}",
                                "username": u["username"], "password": u["password"]})
        return f"UPDATED {u['display_name']}: {'; '.join(u['changes'])}"
    return f"ERROR: unknown tool {name}"


def execute_tool(user: User, name: str, raw_args, ctx: ToolContext) -> str:
    if name not in allowed_tool_names(user):
        audit(user.id, "ai_access_denied", f"tool {name} not allowed for role {user.role_name}")
        return "ERROR: NOT_AUTHORIZED - your role does not allow this."
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
