"""Data-access layer for TASKS. EVERY permission rule lives here, so the REST API, the instant
answers and the AI assistant all go through the same checks:
* Admin -> read all tasks, create / edit / reassign / delete tasks.
* Agent -> read ONLY own tasks and update ONLY status, progress and a note."""
import re
import sqlite3
from datetime import timedelta
from typing import List, Optional

from auth import User
from config import (PRIORITIES, STATUSES, STATUS_COMPLETED, STATUS_NOT_STARTED, STATUS_PARTIAL,
                    STATUS_IN_PROGRESS, STATUS_ON_HOLD, LOCAL_TZ)
from database import get_conn, audit
from errors import BadRequest, Forbidden, NotFound
from notifications import notify, notify_admins
from utils import now_utc, to_iso, parse_dt, fmt_local, humanize_remaining, local_input_value

TASK_SELECT = """SELECT t.*, u.username AS agent_username, u.display_name AS agent_name, u.is_active AS agent_active
                 FROM tasks t JOIN users u ON u.id = t.assigned_to"""


# ---------------------------------------------------------------------------
# User lookup (shared by tasks, user management and AI)
# ---------------------------------------------------------------------------
def resolve_user(conn, name, role: Optional[str] = "agent") -> sqlite3.Row:
    """Find an ACTIVE user by username, display name, 'Agent X' / 'X' shorthand or unique prefix."""
    raw = str(name or "").strip()
    label = role or "user"
    if not raw:
        raise BadRequest(f"{label.capitalize()} is required.")
    key = re.sub(r"\s+", " ", raw.lower())
    sql = "SELECT id, username, display_name, role FROM users WHERE is_active=1"
    rows = conn.execute(sql + (" AND role=?" if role else ""), (role,) if role else ()).fetchall()
    for r in rows:
        if key in (r["username"].lower(), r["display_name"].lower()):
            return r
    m = re.fullmatch(r"(?:agent[\s_\-]*)?([a-z0-9])", key)
    if m:
        for r in rows:
            if r["username"].lower() == f"agent_{m.group(1)}" or r["display_name"].lower() == f"agent {m.group(1)}":
                return r
    matches = [r for r in rows if r["display_name"].lower().startswith(key) or r["username"].lower().startswith(key)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise BadRequest(f"'{raw}' matches more than one {label}: "
                         f"{', '.join(r['display_name'] for r in matches)}. Please be more specific.")
    raise NotFound(f"{label.capitalize()} '{raw}' not found. Active {label}s: "
                   f"{', '.join(r['display_name'] for r in rows) or 'none'}.")


def resolve_agent(conn, agent) -> sqlite3.Row:
    return resolve_user(conn, agent, "agent")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def enrich(row: sqlite3.Row) -> dict:
    t = dict(row)
    done = t["status"] == STATUS_COMPLETED
    remaining = (parse_dt(t["deadline"]) - now_utc()).total_seconds()
    t["is_overdue"] = (not done) and remaining < 0
    t["remaining_seconds"] = None if done else int(remaining)
    t["remaining_human"] = "Completed" if done else humanize_remaining(remaining)
    t["deadline_local"] = fmt_local(t["deadline"])
    t["deadline_input"] = local_input_value(t["deadline"])
    t["created_local"] = fmt_local(t["created_at"])
    t["completed_local"] = fmt_local(t["completed_at"])
    t["updated_local"] = fmt_local(t["updated_at"])
    t["agent_active"] = bool(t.get("agent_active", 1))
    return t


def counts(tasks: List[dict]) -> dict:
    c = {
        "total": len(tasks),
        "completed": sum(t["status"] == STATUS_COMPLETED for t in tasks),
        "in_progress": sum(t["status"] == STATUS_IN_PROGRESS for t in tasks),
        "partially_completed": sum(t["status"] == STATUS_PARTIAL for t in tasks),
        "on_hold": sum(t["status"] == STATUS_ON_HOLD for t in tasks),
        "not_started": sum(t["status"] == STATUS_NOT_STARTED for t in tasks),
        "overdue": sum(bool(t["is_overdue"]) for t in tasks),
    }
    c["pending"] = c["total"] - c["completed"]
    c["completion_rate_pct"] = round(c["completed"] / c["total"] * 100, 1) if c["total"] else 0.0
    c["avg_progress_pct"] = round(sum(t["progress"] for t in tasks) / len(tasks), 1) if tasks else 0.0
    return c


def priority_score(t: dict):
    """Deterministic ranking: overdue > deadline urgency > priority > remaining effort > momentum."""
    reasons = []
    hrs = t["remaining_seconds"] / 3600
    if hrs < 0:
        urgency = 100 + min(abs(hrs), 240) / 240 * 20
        reasons.append(f"overdue ({t['remaining_human'].lower()})")
    elif hrs <= 24:
        urgency = 80
        reasons.append("due within 24 hours")
    elif hrs <= 72:
        urgency = 60
        reasons.append("due within 3 days")
    elif hrs <= 168:
        urgency = 40
        reasons.append("due this week")
    else:
        urgency = 20
        reasons.append("deadline is more than a week away")
    prio_pts = PRIORITIES.get(t["priority"], 2) * 15
    reasons.append(f"{t['priority']} priority")
    effort_pts = 0
    est = t.get("estimated_hours")
    if est:
        left = round(est * (100 - t["progress"]) / 100, 1)
        if hrs > 0 and left >= hrs * 0.5:
            effort_pts = 15
            reasons.append(f"~{left}h of work left vs. {round(hrs, 1)}h to deadline")
    momentum = 0
    if t["status"] in (STATUS_IN_PROGRESS, STATUS_PARTIAL):
        momentum = 5
        reasons.append(f"already {t['progress']}% done")
    if t["status"] == STATUS_ON_HOLD:
        reasons.append("on hold - resolve the blocker")
    return round(urgency + prio_pts + effort_pts + momentum, 1), reasons


def normalize_status_progress(status: str, progress, current_progress: int) -> int:
    if status not in STATUSES:
        raise BadRequest(f"Invalid status. Allowed: {', '.join(STATUSES)}.")
    if progress is not None:
        try:
            progress = int(progress)
        except (TypeError, ValueError):
            raise BadRequest("Progress must be a whole number between 0 and 100.")
        if not 0 <= progress <= 100:
            raise BadRequest("Progress must be between 0 and 100.")
    if status == STATUS_COMPLETED:
        return 100
    if status == STATUS_NOT_STARTED:
        return 0
    p = current_progress if progress is None else progress
    if p >= 100:
        raise BadRequest("100% progress means the task is done - please choose status 'Completed'.")
    if status == STATUS_PARTIAL and p < 1:
        raise BadRequest("For 'Partially Completed', set progress between 1% and 99%.")
    return p


def _parse_hours(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise BadRequest("Estimated hours must be a number.")
    if v < 0 or v > 10000:
        raise BadRequest("Estimated hours must be between 0 and 10000.")
    return v


# ---------------------------------------------------------------------------
# Dashboard insights (charts)
# ---------------------------------------------------------------------------
def _local_date(iso: str):
    return parse_dt(iso).astimezone(LOCAL_TZ).date()


def insights(tasks: List[dict]) -> dict:
    """7-day completion trend, 7-day deadline calendar, priority mix and 'needs attention' list."""
    today = now_utc().astimezone(LOCAL_TZ).date()
    past = [today - timedelta(days=i) for i in range(6, -1, -1)]
    nxt = [today + timedelta(days=i) for i in range(7)]
    done = [t for t in tasks if t["status"] == STATUS_COMPLETED and t["completed_at"]]
    pending = [t for t in tasks if t["status"] != STATUS_COMPLETED]
    trend = [{"day": d.strftime("%a"), "date": d.strftime("%d %b"),
              "count": sum(_local_date(t["completed_at"]) == d for t in done)} for d in past]
    calendar = []
    for d in nxt:
        due = [t for t in pending if _local_date(t["deadline"]) == d and t["remaining_seconds"] >= 0]
        calendar.append({"day": d.strftime("%a"), "date": d.strftime("%d"), "month": d.strftime("%b"),
                         "count": len(due), "critical": sum(t["priority"] in ("Critical", "High") for t in due),
                         "titles": [t["title"] for t in due][:4]})
    mix = {p: sum(t["priority"] == p for t in pending) for p in PRIORITIES}
    attention = []
    for t in sorted(pending, key=lambda x: x["remaining_seconds"]):
        reason = ("overdue" if t["is_overdue"] else "due in 24h" if t["remaining_seconds"] <= 86400
                  else "on hold" if t["status"] == STATUS_ON_HOLD else None)
        if reason:
            attention.append({"id": t["id"], "title": t["title"], "agent": t["agent_name"], "reason": reason,
                              "priority": t["priority"], "status": t["status"], "time_left": t["remaining_human"]})
    week_done = sum(x["count"] for x in trend)
    return {"trend": trend, "week_completed": week_done, "calendar": calendar, "priority_mix": mix,
            "attention": attention[:8], "overdue_to_pending_pct": round(sum(t["is_overdue"] for t in pending) /
                                                                        len(pending) * 100) if pending else 0}


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
class TaskRepository:
    def __init__(self, user: User):
        self.user = user

    def _require_admin(self):
        if not self.user.is_admin:
            raise Forbidden("Only Admins can perform this action.")

    # ---- reads -----------------------------------------------------------------
    def list_tasks(self, status=None, priority=None, agent=None, overdue_only=False,
                   pending_only=False, search=None) -> List[dict]:
        sql, params = TASK_SELECT + " WHERE 1=1", []
        with get_conn() as conn:
            if self.user.is_admin:
                if agent:
                    sql += " AND t.assigned_to=?"
                    params.append(resolve_agent(conn, agent)["id"])
            else:
                if agent:
                    target = resolve_agent(conn, agent)
                    if target["id"] != self.user.id:
                        raise Forbidden(f"You are not authorized to access {target['display_name']}'s task "
                                        f"information. You can view and analyze your own assigned tasks.")
                sql += " AND t.assigned_to=?"   # hard row-level filter for agents
                params.append(self.user.id)
            if status:
                if status not in STATUSES:
                    raise BadRequest(f"Invalid status. Allowed: {', '.join(STATUSES)}.")
                sql += " AND t.status=?"
                params.append(status)
            if priority:
                if priority not in PRIORITIES:
                    raise BadRequest(f"Invalid priority. Allowed: {', '.join(PRIORITIES)}.")
                sql += " AND t.priority=?"
                params.append(priority)
            if pending_only:
                sql += " AND t.status != ?"
                params.append(STATUS_COMPLETED)
            if search:
                sql += " AND (t.title LIKE ? OR t.description LIKE ?)"
                params += [f"%{search}%", f"%{search}%"]
            rows = conn.execute(sql + " ORDER BY t.deadline ASC", params).fetchall()
        tasks = [enrich(r) for r in rows]
        return [t for t in tasks if t["is_overdue"]] if overdue_only else tasks

    def get_task(self, task_id) -> dict:
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            raise BadRequest("Task id must be a number.")
        with get_conn() as conn:
            row = conn.execute(TASK_SELECT + " WHERE t.id=?", (task_id,)).fetchone()
        if not row or (not self.user.is_admin and row["assigned_to"] != self.user.id):
            raise NotFound(f"Task #{task_id} not found.")
        return enrich(row)

    def task_history(self, task_id) -> List[dict]:
        self.get_task(task_id)
        with get_conn() as conn:
            rows = conn.execute("""SELECT h.*, u.display_name AS by_name FROM task_updates h JOIN users u ON u.id = h.user_id
                                   WHERE h.task_id=? ORDER BY h.id DESC""", (int(task_id),)).fetchall()
        return [{**dict(r), "created_local": fmt_local(r["created_at"])} for r in rows]

    def summary(self, agent=None) -> dict:
        tasks = self.list_tasks(agent=agent)
        pending = [t for t in tasks if t["status"] != STATUS_COMPLETED]
        return {"counts": counts(tasks),
                "pending_tasks": [{"id": t["id"], "title": t["title"], "agent": t["agent_name"], "status": t["status"],
                                   "progress": t["progress"], "priority": t["priority"], "deadline": t["deadline_local"],
                                   "time_left": t["remaining_human"]} for t in pending]}

    def prioritized(self, agent=None) -> List[dict]:
        ranked = []
        for t in self.list_tasks(agent=agent, pending_only=True):
            score, reasons = priority_score(t)
            ranked.append({"rank": 0, "id": t["id"], "title": t["title"], "agent": t["agent_name"],
                           "priority": t["priority"], "status": t["status"], "progress": t["progress"],
                           "deadline": t["deadline_local"], "time_left": t["remaining_human"],
                           "overdue": t["is_overdue"], "score": score, "reasons": reasons})
        ranked.sort(key=lambda x: x["score"], reverse=True)
        for i, item in enumerate(ranked, 1):
            item["rank"] = i
        return ranked

    def upcoming(self, hours: int = 72) -> List[dict]:
        hours = max(1, min(int(hours), 24 * 60))
        return [t for t in self.list_tasks(pending_only=True) if 0 <= t["remaining_seconds"] <= hours * 3600]

    def team_analytics(self) -> dict:
        self._require_admin()
        tasks = self.list_tasks()
        with get_conn() as conn:
            agents = conn.execute("SELECT id, display_name FROM users WHERE role='agent' AND is_active=1 "
                                  "ORDER BY display_name").fetchall()
        per_agent = [{"agent": a["display_name"], **counts([t for t in tasks if t["assigned_to"] == a["id"]])}
                     for a in agents]
        with_tasks = [p for p in per_agent if p["total"]]
        max_pending = max((p["pending"] for p in per_agent), default=0)
        return {
            "team_totals": counts(tasks), "per_agent": per_agent,
            "agents_all_tasks_completed": [p["agent"] for p in with_tasks if p["pending"] == 0],
            "agents_with_not_started_tasks": [p["agent"] for p in per_agent if p["not_started"]],
            "agents_with_highest_pending": [p["agent"] for p in per_agent if max_pending and p["pending"] == max_pending],
            "agents_without_tasks": [p["agent"] for p in per_agent if not p["total"]],
            "overdue_tasks": [{"id": t["id"], "title": t["title"], "agent": t["agent_name"], "status": t["status"],
                               "progress": t["progress"], "priority": t["priority"], "deadline": t["deadline_local"],
                               "overdue_by": t["remaining_human"]} for t in tasks if t["is_overdue"]],
        }

    # ---- dashboards ----------------------------------------------------------
    def admin_dashboard(self) -> dict:
        self._require_admin()
        team = self.team_analytics()
        tasks = self.list_tasks()
        with get_conn() as conn:
            recent = [{**dict(r), "created_local": fmt_local(r["created_at"])} for r in conn.execute(
                """SELECT h.*, u.display_name AS by_name, t.title FROM task_updates h JOIN users u ON u.id=h.user_id
                   JOIN tasks t ON t.id=h.task_id ORDER BY h.id DESC LIMIT 8""").fetchall()]
        return {"counts": team["team_totals"], "per_agent": team["per_agent"], "overdue": team["overdue_tasks"],
                "upcoming": [self._brief(t) for t in self.upcoming(72)], "recent_activity": recent,
                "insights": insights(tasks)}

    def agent_dashboard(self) -> dict:
        if not self.user.is_agent:
            raise Forbidden("This dashboard is for agents only.")
        tasks = self.list_tasks()
        return {"counts": counts(tasks), "top_priorities": self.prioritized()[:5],
                "upcoming": [self._brief(t) for t in self.upcoming(72)],
                "overdue": [self._brief(t) for t in tasks if t["is_overdue"]], "insights": insights(tasks)}

    @staticmethod
    def _brief(t: dict) -> dict:
        return {"id": t["id"], "title": t["title"], "agent": t["agent_name"], "priority": t["priority"],
                "status": t["status"], "progress": t["progress"], "deadline": t["deadline_local"],
                "time_left": t["remaining_human"], "is_overdue": t["is_overdue"], "remaining_seconds": t["remaining_seconds"]}

    # ---- writes: admin --------------------------------------------------------
    def create_task(self, data: dict) -> dict:
        self._require_admin()
        title = (data.get("title") or "").strip()
        if not title:
            raise BadRequest("Title is required.")
        if len(title) > 200:
            raise BadRequest("Title must be 200 characters or fewer.")
        priority = data.get("priority") or "Medium"
        if priority not in PRIORITIES:
            raise BadRequest(f"Invalid priority. Allowed: {', '.join(PRIORITIES)}.")
        deadline = parse_dt(data.get("deadline"))
        if deadline <= now_utc():
            raise BadRequest("Deadline must be in the future.")
        est = _parse_hours(data.get("estimated_hours"))
        n = now_utc()
        with get_conn() as conn:
            agent = resolve_agent(conn, data.get("assigned_to"))
            cur = conn.execute(
                """INSERT INTO tasks(title, description, assigned_to, created_by, created_at, deadline, priority,
                   status, progress, estimated_hours, completed_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title, (data.get("description") or "").strip(), agent["id"], self.user.id, to_iso(n),
                 to_iso(deadline), priority, STATUS_NOT_STARTED, 0, est, None, to_iso(n)))
            task_id = cur.lastrowid
            conn.execute("INSERT INTO task_updates(task_id, user_id, action, status, progress, note, created_at) "
                         "VALUES (?,?,?,?,?,?,?)", (task_id, self.user.id, "created", STATUS_NOT_STARTED, 0,
                                                    f"Created and assigned to {agent['display_name']}", to_iso(n)))
        task = self.get_task(task_id)
        notify(agent["id"], task_id, "assigned",
               f"New task assigned: #{task_id} '{title}' | Priority: {priority} | Deadline: {task['deadline_local']}")
        audit(self.user.id, "task_create", f"#{task_id} -> {agent['username']}")
        return task

    def admin_update_task(self, task_id, data: dict) -> dict:
        self._require_admin()
        old = self.get_task(task_id)
        sets, params, notes, events = [], [], [], []
        with get_conn() as conn:
            if data.get("title") is not None:
                title = str(data.get("title") or "").strip()
                if not title:
                    raise BadRequest("Title cannot be empty.")
                if len(title) > 200:
                    raise BadRequest("Title must be 200 characters or fewer.")
                if title != old["title"]:
                    sets.append("title=?"); params.append(title); notes.append(f"title -> '{title}'")
            if data.get("description") is not None and str(data["description"]).strip() != old["description"]:
                sets.append("description=?"); params.append(str(data["description"]).strip())
                notes.append("description changed")
            if data.get("priority") and data["priority"] != old["priority"]:
                if data["priority"] not in PRIORITIES:
                    raise BadRequest(f"Invalid priority. Allowed: {', '.join(PRIORITIES)}.")
                sets.append("priority=?"); params.append(data["priority"])
                notes.append(f"priority {old['priority']} -> {data['priority']}")
                events.append(("priority", data["priority"]))
            if data.get("deadline"):
                new_deadline = parse_dt(data["deadline"])
                if new_deadline != parse_dt(old["deadline"]):
                    sets.append("deadline=?"); params.append(to_iso(new_deadline))
                    notes.append(f"deadline -> {fmt_local(to_iso(new_deadline))}")
                    events.append(("deadline", None))
            if "estimated_hours" in data:
                est = _parse_hours(data.get("estimated_hours"))
                if est != old["estimated_hours"]:
                    sets.append("estimated_hours=?"); params.append(est); notes.append("estimate changed")
            if data.get("assigned_to"):
                agent = resolve_agent(conn, data["assigned_to"])
                if agent["id"] != old["assigned_to"]:
                    sets.append("assigned_to=?"); params.append(agent["id"])
                    notes.append(f"reassigned {old['agent_name']} -> {agent['display_name']}")
                    events.append(("reassigned", agent))
            progress_in = None if data.get("progress") == "" else data.get("progress")
            if (data.get("status") and data["status"] != old["status"]) or progress_in is not None:
                status = data.get("status") or old["status"]
                progress = normalize_status_progress(status, progress_in, old["progress"])
                if status != old["status"] or progress != old["progress"]:
                    completed_at = (old["completed_at"] or to_iso(now_utc())) if status == STATUS_COMPLETED else None
                    sets += ["status=?", "progress=?", "completed_at=?"]
                    params += [status, progress, completed_at]
                    notes.append(f"status {status} ({progress}%)")
            if not sets:
                return old
            n = to_iso(now_utc())
            sets.append("updated_at=?"); params.append(n)
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params + [old["id"]])
            conn.execute("INSERT INTO task_updates(task_id, user_id, action, status, progress, note, created_at) "
                         "SELECT id, ?, 'edited', status, progress, ?, ? FROM tasks WHERE id=?",
                         (self.user.id, "; ".join(notes), n, old["id"]))
        task = self.get_task(old["id"])
        for ev, payload in events:
            if ev == "reassigned":
                notify(payload["id"], task["id"], "assigned",
                       f"Task #{task['id']} '{task['title']}' has been assigned to you. Deadline: {task['deadline_local']}")
                if old["agent_active"]:
                    notify(old["assigned_to"], task["id"], "reassigned",
                           f"Task #{task['id']} '{old['title']}' has been reassigned to {payload['display_name']}.")
            elif ev == "priority":
                notify(task["assigned_to"], task["id"], "priority_changed",
                       f"Priority of task #{task['id']} '{task['title']}' changed to {payload}.")
            elif ev == "deadline":
                notify(task["assigned_to"], task["id"], "deadline_changed",
                       f"Deadline of task #{task['id']} '{task['title']}' changed to {task['deadline_local']}.")
        task["changes"] = notes
        audit(self.user.id, "task_edit", f"#{task['id']}: {'; '.join(notes)}")
        return task

    def delete_task(self, task_id) -> dict:
        self._require_admin()
        task = self.get_task(task_id)
        with get_conn() as conn:
            conn.execute("DELETE FROM notifications WHERE task_id=?", (task["id"],))
            conn.execute("DELETE FROM task_updates WHERE task_id=?", (task["id"],))
            conn.execute("DELETE FROM tasks WHERE id=?", (task["id"],))
        if task["agent_active"]:
            notify(task["assigned_to"], None, "task_removed", f"Task #{task['id']} '{task['title']}' was removed by Admin.")
        audit(self.user.id, "task_delete", f"#{task['id']} {task['title']}")
        return task

    # ---- writes: agent (status / progress / note only) --------------------------
    def agent_update_progress(self, task_id, data: dict) -> dict:
        if not self.user.is_agent:
            raise Forbidden("Only the assigned agent can post progress updates. Admins should use Edit Task.")
        illegal = set(k for k, v in data.items() if v not in (None, "")) - {"status", "progress", "note"}
        if illegal:
            raise Forbidden(f"Agents can only update status, progress and add a note (not: {', '.join(sorted(illegal))}).")
        old = self.get_task(task_id)
        status = data.get("status") or old["status"]
        progress_in = None if data.get("progress") in (None, "") else data.get("progress")
        progress = normalize_status_progress(status, progress_in, old["progress"])
        note = (data.get("note") or "").strip()[:1000]
        if status == old["status"] and progress == old["progress"] and not note:
            raise BadRequest("Nothing to update - change the status/progress or add a note.")
        n = to_iso(now_utc())
        completed_at = (old["completed_at"] or n) if status == STATUS_COMPLETED else None
        with get_conn() as conn:
            conn.execute("UPDATE tasks SET status=?, progress=?, completed_at=?, updated_at=? WHERE id=? AND assigned_to=?",
                         (status, progress, completed_at, n, old["id"], self.user.id))
            conn.execute("INSERT INTO task_updates(task_id, user_id, action, status, progress, note, created_at) "
                         "VALUES (?,?,?,?,?,?,?)", (old["id"], self.user.id, "progress", status, progress, note or None, n))
        task = self.get_task(old["id"])
        if status != old["status"]:
            if status == STATUS_COMPLETED:
                notify_admins(task["id"], "completed", f"{self.user.display_name} completed task #{task['id']} '{task['title']}'.")
            elif status == STATUS_ON_HOLD:
                notify_admins(task["id"], "on_hold", f"{self.user.display_name} put task #{task['id']} '{task['title']}' on hold"
                              + (f": {note}" if note else "."))
            else:
                notify_admins(task["id"], "status_changed", f"{self.user.display_name} updated task #{task['id']} "
                                                             f"'{task['title']}' to {status} ({progress}%).")
        audit(self.user.id, "task_progress", f"#{task['id']}: {old['status']} -> {status} ({progress}%)")
        return task
