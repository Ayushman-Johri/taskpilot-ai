"""Audit log reads for the AI (instant answers and the get_audit_log tool). Needs audit.view."""
import re

from auth import User
from database import get_conn
from errors import Forbidden
from utils import fmt_short

TASK_REF_RE = re.compile(r"(?:#|\btask\s*(?:id|no\.?|number)?\s*#?\s*)(\d+)", re.I)


def read_audit(user: User, task_id=None, person=None, action=None, limit=20) -> list:
    if not user.has("audit.view"):
        raise Forbidden("Your role does not include access to the audit log.")
    sql = """SELECT a.created_at, a.action, a.detail, u.display_name FROM audit_log a
             LEFT JOIN users u ON u.id=a.user_id WHERE a.action NOT IN ('login','logout','ai_query','ai_greeting')"""
    params = []
    if task_id:
        sql += " AND (a.detail LIKE ? OR a.detail LIKE ?)"
        params += [f"#{int(task_id)}:%", f"#{int(task_id)} %"]
    if person:
        sql += " AND (lower(u.display_name) LIKE ? OR lower(u.username) LIKE ? OR lower(a.detail) LIKE ?)"
        params += [f"%{str(person).lower()}%"] * 3
    if action:
        sql += " AND a.action LIKE ?"
        params.append(f"%{action}%")
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(max(1, min(int(limit or 20), 50)))
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{"when": fmt_short(r["created_at"]), "who": r["display_name"] or "-", "action": r["action"],
             "detail": (r["detail"] or "")[:140]} for r in rows]


def audit_markdown(user: User, message: str) -> str:
    m = TASK_REF_RE.search(message)
    task_id = int(m.group(1)) if m else None
    rows = read_audit(user, task_id=task_id, limit=20)
    scope = f"for task #{task_id}" if task_id else "(latest)"
    if not rows:
        return f"**No audit entries found {scope}.**"
    body = "\n".join(f"| {r['when']} | {r['who']} | {r['action']} | {r['detail'].replace('|', '/')} |" for r in rows)
    return (f"**Audit log {scope} - {len(rows)} entries.**\n\n| When | Who | Action | Detail |\n|---|---|---|---|\n{body}"
            + ("\n\n_Open the Activity Log page for the full history._" if not task_id else ""))
