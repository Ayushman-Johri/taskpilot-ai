"""Instant answers: the most common questions are answered directly from the database with
ZERO LLM tokens (summary, overdue, not started, in progress, completed, on hold, due soon,
priorities, and admin team questions). Anything not clearly matched goes to the LLM.

Every answer is built through TaskRepository, so the same permission rules apply."""
import re
from typing import List, Optional

from auth import User
from config import STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NOT_STARTED, STATUS_ON_HOLD, STATUS_PARTIAL
from database import get_conn
from repository import TaskRepository, counts

R = lambda p: re.compile(p, re.I)
INTENTS = [  # (name, pattern) - checked in this order
    ("rate", R(r"completion\s*rate|percent(age)?|kitna\s+%|% complete")),
    ("highest", R(r"\b(highest|most|maximum|max|sabse\s+(zyada|jyada))\b.*\b(pending|tasks?|kaam|workload)|"
                  r"\b(pending|workload)\b.*\b(highest|most|sabse\s+(zyada|jyada))\b")),
    ("all_done", R(r"\b(completed|finished|done)\s+(all|every)|all\s+(their|of\s+their|tasks)\s+(completed|done)|"
                   r"sab\s+(kaam\s+)?(complete|poore|khatam)")),
    ("workload", R(r"\bworkload|agent[\s-]?wise|per\s+agent|each\s+agent|har\s+agent|team\s+(summary|overview|status|report)")),
    ("priority", R(r"\bprioriti[sz]e|\bpriority\s+order|order\s+of\s+priority|what\s+should\s+i\s+(do|complete|work)|"
                   r"(complete|do|work\s+on)\s+first|kya\s+pehle|pehle\s+kya|plan\s+my\s+day|focus\s+(on|next)")),
    ("overdue", R(r"\boverdue|\blate\b|missed\s+deadline|deadline\s+(miss|nikal|cross)|time\s+(nikal|khatam)")),
    ("upcoming", R(r"\bdue\s+(soon|today|tomorrow|this\s+week)|upcoming|next\s+\d+\s+(hours?|days?)|"
                   r"\b(aaj|kal)\b.*\b(due|deadline)|deadlines?\s+(soon|this\s+week|aaj|kal)")),
    ("not_started", R(r"not\s+(been\s+)?started|haven'?t\s+started|shuru\s+nahi|start\s+nahi")),
    ("in_progress", R(r"in\s+progress|ongoing|chal\s+rah[eia]|working\s+on")),
    ("partial", R(r"partial(ly)?")),
    ("on_hold", R(r"on\s+hold|blocked|ruk[ea]\s+hu[ea]")),
    ("completed", R(r"\b(completed|finished|done)\b|ho\s+gaye|poore\s+ho")),
    ("summary", R(r"\bsummar(y|ise|ize)|overview|status\s+report|quick\s+report|kya\s+haal|how\s+many\s+tasks|"
                  r"kitne\s+(task|kaam)|tasks?\s+assigned\s+to\s+me|count\s+of\s+tasks")),
]
LLM_ONLY = R(r"\b(compare|why\s+is|explain|reason\s+for|suggest|recommend|should\s+(we|i)\s+(re)?assign|"
             r"history|note|comment|estimate|description|how\s+long|predict|trend|improve)\b|#\d+")
STATUS_OF = {"not_started": STATUS_NOT_STARTED, "in_progress": STATUS_IN_PROGRESS, "partial": STATUS_PARTIAL,
             "on_hold": STATUS_ON_HOLD, "completed": STATUS_COMPLETED}
LABEL = {"overdue": "overdue", "not_started": "not started", "in_progress": "in progress",
         "partial": "partially completed", "on_hold": "on hold", "completed": "completed", "upcoming": "due in the next 72 hours"}


def _table(tasks: List[dict], admin: bool, done: bool = False) -> str:
    head = "| # | Task |" + (" Agent |" if admin else "") + " Status | Priority | " + ("Completed |" if done else "Due / left |")
    sep = "|---|---|" + ("---|" if admin else "") + "---|---|---|"
    rows = []
    for t in tasks[:25]:
        when = (t["completed_local"] or "-") if done else f"{t['deadline_local']} · {t['remaining_human']}"
        rows.append(f"| {t['id']} | {t['title']} |" + (f" {t['agent_name']} |" if admin else "")
                    + f" {t['status']} ({t['progress']}%) | {t['priority']} | {when} |")
    more = f"\n\n_…and {len(tasks) - 25} more._" if len(tasks) > 25 else ""
    return "\n".join([head, sep, *rows]) + more


def _agent_filter(user: User, message: str) -> Optional[dict]:
    if not user.is_admin:
        return None
    text = message.lower()
    with get_conn() as conn:
        rows = conn.execute("SELECT username, display_name FROM users WHERE role='agent' AND is_active=1").fetchall()
    for r in rows:
        for name in (r["display_name"], r["username"]):
            if re.search(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)", text):
                return {"username": r["username"], "name": r["display_name"]}
    return None


def detect(message: str) -> List[str]:
    if len(message) > 160 or LLM_ONLY.search(message):
        return []
    found = [name for name, rx in INTENTS if rx.search(message)]
    if "all_done" in found or "rate" in found:
        found = [f for f in found if f not in ("completed", "summary")]
    if "highest" in found or "workload" in found:
        found = [f for f in found if f not in ("summary", "workload")] or found
    return found[:2]


def answer(user: User, message: str) -> Optional[str]:
    intents = detect(message)
    if not intents:
        return None
    repo = TaskRepository(user)
    who = _agent_filter(user, message)
    agent = who["username"] if who else None
    scope = f"{who['name']}'s" if who else ("the team's" if user.is_admin else "your")
    team_only = {"rate", "highest", "all_done", "workload"}
    if any(i in team_only for i in intents):
        if not user.is_admin:
            return None   # let the agent guard / LLM handle it
        if who and set(intents) & {"highest", "all_done", "workload"}:
            return None
    tasks = repo.list_tasks(agent=agent)
    pending = [t for t in tasks if t["status"] != STATUS_COMPLETED]
    out = []
    for intent in intents:
        if intent == "summary":
            c = counts(tasks)
            out.append(f"**{c['total']} tasks in {scope} list - {c['completed']} completed, {c['pending']} pending"
                       f"{', ' + str(c['overdue']) + ' overdue' if c['overdue'] else ''}.**\n\n"
                       f"| Completed | In progress | Partial | On hold | Not started | Overdue |\n|---|---|---|---|---|---|\n"
                       f"| {c['completed']} | {c['in_progress']} | {c['partially_completed']} | {c['on_hold']} | "
                       f"{c['not_started']} | {c['overdue']} |")
            if pending:
                out.append("**Pending tasks**\n\n" + _table(pending, user.is_admin and not who))
        elif intent == "priority":
            ranked = repo.prioritized(agent=agent)
            if not ranked:
                out.append(f"**No pending tasks in {scope} list 🎉**")
                continue
            lines = [f"**Do these first (ranked by deadline, priority and effort left):**", "",
                     "| Rank | Task |" + (" Agent |" if user.is_admin and not who else "") + " Why |", "|---|---|"
                     + ("---|" if user.is_admin and not who else "") + "---|"]
            for r in ranked[:8]:
                lines.append(f"| {r['rank']} | {r['title']} (#{r['id']}) |" + (f" {r['agent']} |" if user.is_admin and not who else "")
                             + f" {', '.join(r['reasons'])} |")
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
                names = a["agents_with_highest_pending"]
                top = max((p["pending"] for p in a["per_agent"]), default=0)
                out.append(f"**{', '.join(names)} {'has' if len(names) == 1 else 'have'} the most pending tasks ({top}).**"
                           if names else "**No agent has pending tasks.**")
            elif intent == "all_done":
                names = a["agents_all_tasks_completed"]
                out.append(f"**{', '.join(names)} completed all assigned tasks.**" if names
                           else "**No agent has completed all of their tasks yet.**")
            if intent == "workload":
                c = a["team_totals"]
                out.append(f"**Team: {c['total']} tasks - {c['completed']} completed, {c['pending']} pending, "
                           f"{c['overdue']} overdue ({c['completion_rate_pct']}% done).**")
            if intent == "workload" or intent == "highest":
                rows = "\n".join(f"| {p['agent']} | {p['total']} | {p['pending']} | {p['overdue']} | {p['completion_rate_pct']}% |"
                                 for p in a["per_agent"])
                out.append("| Agent | Total | Pending | Overdue | Completed % |\n|---|---|---|---|---|\n" + rows)
        else:
            if intent == "overdue":
                sel = [t for t in tasks if t["is_overdue"]]
            elif intent == "upcoming":
                sel = [t for t in pending if 0 <= t["remaining_seconds"] <= 72 * 3600]
            else:
                sel = [t for t in tasks if t["status"] == STATUS_OF[intent]]
            n = len(sel)
            head = f"**{n} {'task is' if n == 1 else 'tasks are'} {LABEL[intent]}" + (f" in {scope} list" if who or not user.is_admin else " across the team") + ".**"
            if user.is_admin and not who and intent in ("not_started", "overdue") and sel:
                agents = sorted({t["agent_name"] for t in sel})
                head += f"\n\n- Agents involved: {', '.join(agents)}"
            out.append(head + ("\n\n" + _table(sel, user.is_admin and not who, intent == "completed") if sel else " 🎉"))
    return "\n\n".join(out)
