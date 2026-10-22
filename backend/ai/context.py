"""Compact, variable part of a request (goes at the END of the prompt). Pipe rows instead of JSON."""
import re

from auth import User
from config import SNAPSHOT_MAX_ROWS, LOCAL_TZ, STATUS_COMPLETED
from database import get_conn
from repository import TaskRepository, counts
from utils import now_utc, fmt_short
from .audit_view import read_audit
from .tools import row_line


def now_line() -> str:
    n = now_utc().astimezone(LOCAL_TZ)
    return f"NOW {n.strftime('%a %Y-%m-%d %H:%M')} {LOCAL_TZ.key}"


def people_line(user: User) -> str:
    if not user.has_any("tasks.view_all", "users.view", "tasks.create"):
        return f"ME {user.display_name}"
    with get_conn() as conn:
        rows = conn.execute("""SELECT u.display_name, r.name AS role FROM users u JOIN roles r ON r.id=u.role_id
                               WHERE u.is_active=1 ORDER BY r.name, u.display_name""").fetchall()
    return f"ME {user.display_name}\nPEOPLE " + ", ".join(f"{r['display_name']} ({r['role']})" for r in rows)


def snapshot(user: User, question: str) -> str:
    q = question.lower()
    lines = [now_line(), f"ME {user.display_name} (role {user.role_name})"]
    if user.has_any("tasks.view_all", "tasks.view_own"):
        repo = TaskRepository(user)
        tasks = repo.list_tasks()
        c = counts(tasks)
        lines.append(f"COUNTS total={c['total']} done={c['completed']} in_progress={c['in_progress']} partial={c['partially_completed']} "
                     f"on_hold={c['on_hold']} not_started={c['not_started']} overdue={c['overdue']} rate={c['completion_rate_pct']}%")
        if user.sees_all_tasks:
            a = repo.team_analytics()
            lines.append("PER_ASSIGNEE name:total/pending/overdue/done%  " + "  ".join(
                f"{p['agent']}:{p['total']}/{p['pending']}/{p['overdue']}/{p['completion_rate_pct']}" for p in a["per_agent"]))
        want_done = bool(re.search(r"complet|done|finish|ho gaye|history|last week|past", q))
        rows = [t for t in tasks if want_done or t["status"] != STATUS_COMPLETED]
        rows.sort(key=lambda t: (t["status"] == STATUS_COMPLETED, t["remaining_seconds"] or 0))
        lines.append(f"TASKS ({'all' if want_done else 'pending'}, {len(rows)})")
        lines += [row_line(t) for t in rows[:SNAPSHOT_MAX_ROWS]]
        for tid in re.findall(r"#(\d+)", question)[:3]:
            try:
                hist = repo.task_history(int(tid))[:5]
                lines.append(f"HISTORY #{tid}: " + " ; ".join(
                    f"{fmt_short(h['created_at'])} {h['by_name']} {h['status'] or ''} {h['progress'] or ''}% {h['note'] or ''}".strip() for h in hist))
            except Exception:
                lines.append(f"HISTORY #{tid}: not found")
    else:
        lines.append("TASKS: this role has no task access")
    if user.has("audit.view") and re.search(r"audit|log|who changed|activity", q):
        lines.append("AUDIT when|who|action|detail")
        lines += [f"{r['when']}|{r['who']}|{r['action']}|{r['detail']}" for r in read_audit(user, limit=20)]
    if user.has("users.view") and re.search(r"user|member|people|role|admin|team", q):
        lines.append(people_line(user).split("\n", 1)[-1])
    return "\n".join(lines)
