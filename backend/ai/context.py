"""Builds the compact, variable part of a request (goes at the END of the prompt).
Pipe-separated rows instead of JSON: roughly 3-4x fewer tokens for the same data."""
import re

from auth import User
from config import SNAPSHOT_MAX_ROWS, LOCAL_TZ, STATUS_COMPLETED
from database import get_conn
from repository import TaskRepository, counts
from utils import now_utc, fmt_short
from .tools import row_line


def now_line() -> str:
    n = now_utc().astimezone(LOCAL_TZ)
    return f"NOW {n.strftime('%a %Y-%m-%d %H:%M')} {LOCAL_TZ.key}"


def people_line() -> str:
    with get_conn() as conn:
        rows = conn.execute("SELECT display_name, role FROM users WHERE is_active=1 ORDER BY role, display_name").fetchall()
    agents = ", ".join(r["display_name"] for r in rows if r["role"] == "agent") or "none"
    admins = ", ".join(r["display_name"] for r in rows if r["role"] == "admin")
    return f"AGENTS {agents}\nADMINS {admins}"


def snapshot(user: User, question: str) -> str:
    """Only the data a read question needs."""
    repo = TaskRepository(user)
    tasks = repo.list_tasks()
    q = question.lower()
    c = counts(tasks)
    lines = [now_line(),
             f"COUNTS total={c['total']} done={c['completed']} in_progress={c['in_progress']} partial={c['partially_completed']} "
             f"on_hold={c['on_hold']} not_started={c['not_started']} overdue={c['overdue']} rate={c['completion_rate_pct']}%"]
    if user.is_admin:
        a = repo.team_analytics()
        lines.append("PER_AGENT agent:total/pending/overdue/done%  " + "  ".join(
            f"{p['agent']}:{p['total']}/{p['pending']}/{p['overdue']}/{p['completion_rate_pct']}" for p in a["per_agent"]))
    want_done = bool(re.search(r"complet|done|finish|ho gaye|history|last week|past", q))
    rows = [t for t in tasks if want_done or t["status"] != STATUS_COMPLETED]
    rows.sort(key=lambda t: (t["status"] == STATUS_COMPLETED, t["remaining_seconds"] or 0))
    lines.append(f"TASKS ({'all' if want_done else 'pending'}, {len(rows)})")
    lines += [row_line(t) for t in rows[:SNAPSHOT_MAX_ROWS]]
    if len(rows) > SNAPSHOT_MAX_ROWS:
        lines.append(f"...{len(rows) - SNAPSHOT_MAX_ROWS} more not shown")
    for tid in re.findall(r"#(\d+)", question)[:3]:     # task history only when a task id is mentioned
        try:
            hist = repo.task_history(int(tid))[:5]
            lines.append(f"HISTORY #{tid}: " + " ; ".join(
                f"{fmt_short(h['created_at'])} {h['by_name']} {h['status'] or ''} {h['progress'] or ''}% {h['note'] or ''}".strip()
                for h in hist))
        except Exception:
            lines.append(f"HISTORY #{tid}: not found")
    return "\n".join(lines)
