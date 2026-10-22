"""Instant answers: common questions answered directly from the database with ZERO LLM tokens.
Everything goes through TaskRepository / audit_view, so the user's permissions apply automatically."""
import re
from typing import List, Optional

from auth import User
from config import STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NOT_STARTED, STATUS_ON_HOLD, STATUS_PARTIAL
from database import get_conn
from errors import AppError
from repository import TaskRepository, counts
from .audit_view import audit_markdown

R = lambda p: re.compile(p, re.I)
INTENTS = [
    ("audit", R(r"\baudit\b|\bactivity\s+log|\blogs?\b.*\b(task|changes?|activity)|\bwho\s+(changed|updated|edited|deleted)|change\s+history")),
    ("rate", R(r"completion\s*rate|percent(age)?\s+(complete|done)|kitna\s+%|% complete")),
    ("highest", R(r"\b(highest|most|maximum|max|sabse\s+(zyada|jyada))\b.*\b(pending|tasks?|kaam|workload)|"
                  r"\b(pending|workload)\b.*\b(highest|most|sabse\s+(zyada|jyada))\b")),
    ("all_done", R(r"\b(completed|finished|done)\s+(all|every)|all\s+(their|of\s+their|tasks)\s+(completed|done)|sab\s+(kaam\s+)?(complete|poore|khatam)")),
    ("workload", R(r"\bworkload|agent[\s-]?wise|per\s+agent|each\s+agent|har\s+agent|team\s+(summary|overview|status|report)")),
    ("priority", R(r"\bprioriti[sz]e|\bpriority\s+order|order\s+of\s+priority|what\s+should\s+i\s+(do|complete|work)|"
                   r"(complete|do|work\s+on)\s+first|kya\s+pehle|pehle\s+kya|plan\s+my\s+day|focus\s+(on|next)")),
    ("overdue", R(r"\boverdue|\blate\b|missed\s+deadline|deadline\s+(miss|nikal|cross)|time\s+(nikal|khatam)")),
    ("upcoming", R(r"\bdue\s+(soon|today|tomorrow|this\s+week)|upcoming|next\s+\d+\s+(hours?|days?)|\b(aaj|kal)\b.*\b(due|deadline)")),
    ("not_started", R(r"not\s+(been\s+)?started|haven'?t\s+started|shuru\s+nahi|start\s+nahi")),
    ("in_progress", R(r"\bin\s+progress|ongoing|chal\s+rah[eia]")),
    ("partial", R(r"partial(ly)?")),
    ("on_hold", R(r"on\s+hold|blocked|ruk[ea]\s+hu[ea]")),
    ("completed", R(r"\b(completed|finished|done)\b|ho\s+gaye|poore\s+ho")),
    ("summary", R(r"\bsummar(y|ise|ize)|overview|status\s+report|quick\s+report|kya\s+haal|how\s+many\s+tasks|"
                  r"kitne\s+(task|kaam)|tasks?\s+assigned\s+to\s+me|count\s+of\s+tasks")),
]
LLM_ONLY = R(r"\b(compare|why\s+is|explain|reason\s+for|suggest|recommend|should\s+(we|i)\s+(re)?assign|"
             r"note|comment|estimate|description|how\s+long|predict|trend|improve)\b")
STATUS_OF = {"not_started": STATUS_NOT_STARTED, "in_progress": STATUS_IN_PROGRESS, "partial": STATUS_PARTIAL,
             "on_hold": STATUS_ON_HOLD, "completed": STATUS_COMPLETED}
LABEL = {"overdue": "overdue", "not_started": "not started", "in_progress": "in progress", "partial": "partially completed",
         "on_hold": "on hold", "completed": "completed", "upcoming": "due in the next 72 hours"}
TEAM_ONLY = {"rate", "highest", "all_done", "workload"}


def _table(tasks: List[dict], show_agent: bool, done: bool = False) -> str:
    head = "| # | Task |" + (" Assignee |" if show_agent else "") + " Status | Priority | " + ("Completed |" if done else "Due / left |")
    sep = "|---|---|" + ("---|" if show_agent else "") + "---|---|---|"
    rows = []
    for t in tasks[:25]:
        when = (t["completed_local"] or "-") if done else f"{t['deadline_local']} · {t['remaining_human']}"
        rows.append(f"| {t['id']} | {t['title']} |" + (f" {t['agent_name']} |" if show_agent else "")
                    + f" {t['status']} ({t['progress']}%) | {t['priority']} | {when} |")
    return "\n".join([head, sep, *rows]) + (f"\n\n_…and {len(tasks) - 25} more._" if len(tasks) > 25 else "")


def _person_filter(user: User, message: str) -> Optional[dict]:
    if not user.sees_all_tasks:
        return None
    text = message.lower()
    with get_conn() as conn:
        rows = conn.execute("SELECT username, display_name FROM users WHERE is_active=1").fetchall()
    for r in rows:
        for name in (r["display_name"], r["username"]):
            if len(name) >= 3 and re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", text):
                return {"username": r["username"], "name": r["display_name"]}
    return None


def detect(message: str) -> List[str]:
    if len(message) > 160:
        return []
    found = [name for name, rx in INTENTS if rx.search(message)]
    if "audit" in found:
        return ["audit"]
    if LLM_ONLY.search(message) or re.search(r"#\d+", message):
        return []
    if "all_done" in found or "rate" in found:
        found = [f for f in found if f not in ("completed", "summary")]
    if "highest" in found:
        found = [f for f in found if f not in ("summary", "workload")] or found
    return found[:2]


def answer(user: User, message: str) -> Optional[str]:
    intents = detect(message)
    if not intents:
        return None
    if intents == ["audit"]:
        if not user.has("audit.view"):
            return "**Your role does not include access to the audit log.** Ask an administrator if you need it."
        return audit_markdown(user, message)
    if not user.has_any("tasks.view_all", "tasks.view_own"):
        return "**Your role does not include access to tasks.**"
    if any(i in TEAM_ONLY for i in intents) and not user.sees_all_tasks:
        return None          # personal users: guard/LLM handle team questions
    repo = TaskRepository(user)
    who = _person_filter(user, message)
    if who and set(intents) & {"highest", "all_done", "workload"}:
        return None
    try:
        tasks = repo.list_tasks(agent=who["username"] if who else None)
    except AppError:
        return None
    team_view = user.sees_all_tasks and not who
    scope = f"{who['name']}'s" if who else ("the team's" if user.sees_all_tasks else "your")
    pending = [t for t in tasks if t["status"] != STATUS_COMPLETED]
    out = []
    for intent in intents:
        if intent == "summary":
            c = counts(tasks)
            out.append(f"**{c['total']} tasks in {scope} list - {c['completed']} completed, {c['pending']} pending"
                       f"{', ' + str(c['overdue']) + ' overdue' if c['overdue'] else ''}.**\n\n"
                       f"| Completed | In progress | Partial | On hold | Not started | Overdue |\n|---|---|---|---|---|---|\n"
                       f"| {c['completed']} | {c['in_progress']} | {c['partially_completed']} | {c['on_hold']} | {c['not_started']} | {c['overdue']} |")
            if pending:
                out.append("**Pending tasks**\n\n" + _table(pending, team_view))
        elif intent == "priority":
            ranked = repo.prioritized(agent=who["username"] if who else None)
            if not ranked:
                out.append(f"**No pending tasks in {scope} list 🎉**")
                continue
            lines = ["**Do these first (ranked by deadline, priority and effort left):**", "",
                     "| Rank | Task |" + (" Assignee |" if team_view else "") + " Why |", "|---|---|" + ("---|" if team_view else "") + "---|"]
            for r in ranked[:8]:
                lines.append(f"| {r['rank']} | {r['title']} (#{r['id']}) |" + (f" {r['agent']} |" if team_view else "") + f" {', '.join(r['reasons'])} |")
            top = ranked[0]
            lines += ["", f"- **Start with:** {top['title']} - {top['time_left'].lower()}, {top['priority']} priority."]
            out.append("\n".join(lines))
        elif intent == "rate":
            c = counts(tasks)
            out.append(f"**{scope.capitalize()} completion rate is {c['completion_rate_pct']}%** "
                       f"({c['completed']} of {c['total']} tasks completed; average progress {c['avg_progress_pct']}%).")
        elif intent in ("highest", "all_done", "workload"):
            a = repo.team_analytics()
            if intent == "highest":
                names, top = a["agents_with_highest_pending"], max((p["pending"] for p in a["per_agent"]), default=0)
                out.append(f"**{', '.join(names)} {'has' if len(names) == 1 else 'have'} the most pending tasks ({top}).**"
                           if names else "**Nobody has pending tasks.**")
            elif intent == "all_done":
                names = a["agents_all_tasks_completed"]
                out.append(f"**{', '.join(names)} completed all assigned tasks.**" if names else "**Nobody has completed all of their tasks yet.**")
            if intent == "workload":
                c = a["team_totals"]
                out.append(f"**Team: {c['total']} tasks - {c['completed']} completed, {c['pending']} pending, {c['overdue']} overdue ({c['completion_rate_pct']}% done).**")
            if intent in ("workload", "highest"):
                rows = "\n".join(f"| {p['agent']} | {p['total']} | {p['pending']} | {p['overdue']} | {p['completion_rate_pct']}% |" for p in a["per_agent"])
                out.append("| Assignee | Total | Pending | Overdue | Completed % |\n|---|---|---|---|---|\n" + rows)
        else:
            sel = ([t for t in tasks if t["is_overdue"]] if intent == "overdue" else
                   [t for t in pending if 0 <= t["remaining_seconds"] <= 72 * 3600] if intent == "upcoming" else
                   [t for t in tasks if t["status"] == STATUS_OF[intent]])
            n = len(sel)
            head = f"**{n} {'task is' if n == 1 else 'tasks are'} {LABEL[intent]}" + (" across the team" if team_view else f" in {scope} list") + ".**"
            out.append(head + ("\n\n" + _table(sel, team_view, intent == "completed") if sel else " 🎉"))
    return "\n\n".join(out)
