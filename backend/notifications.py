"""In-app notifications, optional Microsoft Teams webhook and the deadline watcher thread.
"Managers" = active users whose role has tasks.view_all."""
import json
import threading
import urllib.request
from typing import Optional

from config import TEAMS_WEBHOOK_URL, DEADLINE_WARNING_HOURS, WATCHER_INTERVAL_SEC, STATUS_COMPLETED
from database import get_conn, users_with_permission
from utils import now_utc, to_iso, parse_dt, fmt_local, humanize_remaining


def _push_teams(message: str) -> None:
    if not TEAMS_WEBHOOK_URL:
        return
    try:
        req = urllib.request.Request(TEAMS_WEBHOOK_URL, data=json.dumps({"text": message}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"[teams-webhook] failed: {exc}")


def notify(user_id: int, task_id: Optional[int], ntype: str, message: str, ref=None, dedupe=False) -> None:
    with get_conn() as conn:
        if dedupe and conn.execute(
                "SELECT 1 FROM notifications WHERE user_id=? AND task_id IS ? AND type=? AND IFNULL(ref,'')=IFNULL(?,'')",
                (user_id, task_id, ntype, ref)).fetchone():
            return
        conn.execute("INSERT INTO notifications(user_id, task_id, type, ref, message, created_at) VALUES (?,?,?,?,?,?)",
                     (user_id, task_id, ntype, ref, message, to_iso(now_utc())))
    _push_teams(message)


def notify_managers(task_id, ntype: str, message: str, ref=None, dedupe=False, exclude=None) -> None:
    with get_conn() as conn:
        ids = users_with_permission(conn, "tasks.view_all")
    for uid in ids:
        if uid != exclude:
            notify(uid, task_id, ntype, message, ref=ref, dedupe=dedupe)


def list_for_user(user_id: int, limit: int = 50) -> dict:
    with get_conn() as conn:
        rows = conn.execute("""SELECT n.*, t.id AS task_exists FROM notifications n LEFT JOIN tasks t ON t.id = n.task_id
                               WHERE n.user_id=? ORDER BY n.id DESC LIMIT ?""", (user_id, limit)).fetchall()
        unread = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user_id,)).fetchone()[0]
    return {"unread": unread, "items": [
        {"id": r["id"], "task_id": r["task_id"] if r["task_exists"] else None, "type": r["type"], "message": r["message"],
         "is_read": bool(r["is_read"]), "created_local": fmt_local(r["created_at"])} for r in rows]}


def mark_read(user_id: int, notification_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notification_id, user_id))


def mark_all_read(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))


def check_deadlines() -> None:
    with get_conn() as conn:
        rows = conn.execute("""SELECT t.id, t.title, t.deadline, t.assigned_to, u.display_name FROM tasks t
                               JOIN users u ON u.id = t.assigned_to WHERE t.status != ? AND u.is_active = 1""",
                            (STATUS_COMPLETED,)).fetchall()
    n = now_utc()
    for r in rows:
        remaining = (parse_dt(r["deadline"]) - n).total_seconds()
        if remaining < 0:
            msg = f"Task #{r['id']} '{r['title']}' is overdue (deadline {fmt_local(r['deadline'])})."
            notify(r["assigned_to"], r["id"], "overdue", msg, ref=r["deadline"], dedupe=True)
            notify_managers(r["id"], "overdue", f"{msg} Assigned to {r['display_name']}.", ref=r["deadline"], dedupe=True)
        elif remaining <= DEADLINE_WARNING_HOURS * 3600:
            msg = f"Task #{r['id']} '{r['title']}' is due soon - {humanize_remaining(remaining)} (deadline {fmt_local(r['deadline'])})."
            notify(r["assigned_to"], r["id"], "deadline_approaching", msg, ref=r["deadline"], dedupe=True)


def start_deadline_watcher() -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                check_deadlines()
            except Exception as exc:
                print(f"[deadline-watcher] error: {exc}")
            stop.wait(WATCHER_INTERVAL_SEC)

    threading.Thread(target=loop, daemon=True, name="deadline-watcher").start()
    return stop
