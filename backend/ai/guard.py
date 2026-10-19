"""Deterministic pre-LLM guard for AGENT users (runs BEFORE any prompt reaches the model)."""
import re
from typing import Optional

from auth import User
from database import get_conn

LETTER_REF_RE = re.compile(r"\bagent(?:[\s_\-]+|)([a-z])\b|\b([a-z])[\s_\-]+agent\b|\bagent\s*#?\s*(\d{1,2})\b", re.I)
TEAM_SCOPE_RE = re.compile(
    r"\b(all agents|other agents?|every agent|each agent|any agent|team[\s\-]?wide|whole team|entire team|"
    r"my team|everyone'?s?|everybody'?s?|sab(hi|ke)?\s+agents?|baaki\s+agents?|dusre\s+agents?|"
    r"doosre\s+agents?|puri\s+team|poori\s+team|team\s+ka|team\s+ke|leaderboard)\b", re.I)
WRITE_INTENT_RE = re.compile(
    r"\b(create|add|assign|reassign|delete|remove|rename|promote|demote)\b.{0,40}\b(tasks?|agents?|users?|admins?)\b|"
    r"\b(tasks?|agents?|users?|admins?)\b.{0,40}\b(create|add|assign|reassign|delete|remove|rename|promote|demote)\b|"
    r"\bmake\s+(me|him|her)\s+(an?\s+)?admin\b|"
    r"\b(task|agent|admin)\s+(banao|bana do|assign karo|add karo|delete karo|hatao|hata do)\b", re.I)
DENY_OTHER = "You are not authorized to access {who} information. You can view and analyze your own assigned tasks."
STOP_WORDS = {"agent", "admin", "team", "task", "tasks", "my", "me", "the"}


def _mentions(text: str, needle: str) -> bool:
    needle = needle.strip().lower()
    if len(needle) < 3 or needle in STOP_WORDS:
        return False
    return re.search(r"(?<![\w])" + re.escape(needle) + r"(?![\w])", text) is not None


def agent_guard(user: User, message: str) -> Optional[str]:
    if not user.is_agent:
        return None
    text = message.lower()
    with get_conn() as conn:
        others = conn.execute("SELECT username, display_name FROM users WHERE id != ? AND is_active=1", (user.id,)).fetchall()
    own_first = user.display_name.split()[0].lower()
    for o in others:
        first = o["display_name"].split()[0]
        if (_mentions(text, o["display_name"]) or _mentions(text, o["username"])
                or (first.lower() != own_first and len(o["display_name"].split()) > 1
                    and first.lower() not in STOP_WORDS and _mentions(text, first))):
            return DENY_OTHER.format(who=f"{o['display_name']}'s task")
    own = re.fullmatch(r"agent\s+([a-z])", user.display_name.lower())
    own_letter = own.group(1) if own else None
    for a, b, num in LETTER_REF_RE.findall(message):
        if (a or b or num).lower() != own_letter:
            return DENY_OTHER.format(who=f"Agent {(a or b or num).upper()}'s task")
    if TEAM_SCOPE_RE.search(message):
        return DENY_OTHER.format(who="other agents' or team-wide task")
    if WRITE_INTENT_RE.search(message):
        return ("Agents cannot create, assign or delete tasks or manage users - only an Admin can do that. "
                "You can update the status, progress and notes of your own tasks from **My Tasks**.")
    return None
