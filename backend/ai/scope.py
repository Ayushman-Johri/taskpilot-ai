"""Topic guardrail (BEFORE the LLM): 'ok' | 'greeting' | 'off_topic'."""
import re
from typing import List

OFF_TOPIC_REPLY = ("I can only help with task management in TaskPilot - tasks, deadlines, priorities, "
                   "progress, people, roles and team analytics. Please ask something related to your work.")
GREETING_REPLY = ("Hello! 👋 Ask me about the tasks you can see - for example *\"Summarize my tasks\"*, "
                  "*\"Which tasks are overdue?\"* or *\"Update task 12 to 70%\"*.")
DOMAIN_RE = re.compile(
    r"\b(tasks?|agents?|admins?|users?|roles?|permissions?|access|audit|logs?|activity|promote|demote|deadlines?|overdue|due|"
    r"priorit(y|ies|ize|ise)|assign(ed|ment)?|reassign|status|pending|progress|complet(e|ed|ion)|not\s+started|on\s+hold|"
    r"in\s+progress|partial(ly)?|workload|team|summar(y|ize|ise)|dashboard|analytics?|notifications?|"
    r"reminders?|password|username|rename|login|members?|kaam|kaamon|kitne|kitna|baaki|bacha|"
    r"critical|urgent|estimate[sd]?|effort|hours?\s+left|time\s+left)\b|#\d+|\d+\s*%", re.I)
OFF_TOPIC_RE = re.compile(
    r"\b(python|java(script)?|c\+\+|html|css|sql|programming|coding|code\s+(for|in|of)|algorithm|leetcode|debug|regex|"
    r"weather|temperature|news|headlines|stock\s+price|share\s+price|bitcoin|crypto|"
    r"cricket|football|ipl|match\s+score|movie|film|song|lyrics|music|netflix|series|"
    r"recipe|cook|food|restaurant|diet|workout|joke|poem|poetry|story|essay|shayari|riddle|"
    r"capital\s+of|president|prime\s+minister|history\s+of|who\s+(is|was|invented)|"
    r"what\s+is\s+the\s+meaning|define\s+\w+|translate|solve|equation|integral|derivative|calculate\s+\d|"
    r"travel|flight|hotel|visa|horoscope|astrology|girlfriend|boyfriend|dating|relationship\s+advice|"
    r"chatgpt|openai|gpt|llm|your\s+(system\s+)?prompt|your\s+instructions|ignore\s+(all\s+|previous\s+)?instructions)\b", re.I)
GREETING_RE = re.compile(
    r"^\s*(hi+|hello+|hey+|namaste|namaskar|good\s+(morning|afternoon|evening)|thanks?|thank\s+you|"
    r"thx|cool|great|bye|goodbye|shukriya|dhanyavaad)[\s!.?🙏👍]*$", re.I)


def classify(message: str, known_names: List[str] = ()) -> str:
    text = (message or "").strip()
    if not text or DOMAIN_RE.search(text):
        return "ok"
    lower = text.lower()
    if any(len(n) >= 3 and re.search(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", lower) for n in known_names):
        return "ok"
    if GREETING_RE.match(text):
        return "greeting"
    return "off_topic" if OFF_TOPIC_RE.search(text) else "ok"
