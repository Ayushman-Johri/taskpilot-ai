"""Rate-limit protection for the Groq API: per-user limit, Groq budget tracking, 429 handling helpers."""
import re
import threading
import time
from collections import defaultdict, deque

from config import AI_USER_MSGS_PER_MIN, AI_MAX_RETRY_WAIT_SEC
from errors import TooManyRequests

_lock = threading.Lock()
_user_calls = defaultdict(deque)
_budget = {"tokens": None, "tokens_reset_at": 0.0, "requests": None, "requests_reset_at": 0.0}


def check_user_limit(user_id: int) -> None:
    """Sliding 60-second window per user (only LLM calls count; instant/cached answers are free)."""
    now = time.monotonic()
    with _lock:
        q = _user_calls[user_id]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= AI_USER_MSGS_PER_MIN:
            wait = int(60 - (now - q[0])) + 1
            raise TooManyRequests(f"You're sending messages too fast. Please wait {wait} seconds.", retry_after=wait)
        q.append(now)


def parse_duration(value) -> float:
    """Groq reset values look like '7.66s', '2m59.56s', '120ms' or plain seconds."""
    if value is None:
        return 0.0
    value = str(value).strip()
    try:
        return float(value)
    except ValueError:
        pass
    return sum(float(n) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[u] for n, u in re.findall(r"([\d.]+)(ms|h|m|s)", value))


def update_from_headers(headers) -> None:
    now = time.monotonic()
    with _lock:
        if headers.get("x-ratelimit-remaining-tokens") is not None:
            _budget["tokens"] = int(float(headers["x-ratelimit-remaining-tokens"]))
            _budget["tokens_reset_at"] = now + parse_duration(headers.get("x-ratelimit-reset-tokens"))
        if headers.get("x-ratelimit-remaining-requests") is not None:
            _budget["requests"] = int(float(headers["x-ratelimit-remaining-requests"]))
            _budget["requests_reset_at"] = now + parse_duration(headers.get("x-ratelimit-reset-requests"))


def wait_for_budget(estimated_tokens: int) -> None:
    now = time.monotonic()
    with _lock:
        waits = []
        if _budget["tokens"] is not None and _budget["tokens"] < estimated_tokens and _budget["tokens_reset_at"] > now:
            waits.append(_budget["tokens_reset_at"] - now)
        if _budget["requests"] is not None and _budget["requests"] < 1 and _budget["requests_reset_at"] > now:
            waits.append(_budget["requests_reset_at"] - now)
    if not waits:
        return
    wait = max(waits)
    if wait > AI_MAX_RETRY_WAIT_SEC:
        raise TooManyRequests(f"The AI is busy right now. Please try again in {int(wait) + 1} seconds.",
                              retry_after=int(wait) + 1)
    time.sleep(wait + 0.2)
    with _lock:
        _budget["tokens"] = None
        _budget["requests"] = None


def estimate_tokens(payload_chars: int, max_output: int) -> int:
    return payload_chars // 4 + max_output
