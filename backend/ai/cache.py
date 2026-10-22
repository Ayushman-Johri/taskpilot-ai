"""Answer cache for repeated questions (0 tokens on a hit).
Scope = users who see the same data share answers:
  - can see all tasks  -> shared by everyone with the SAME permission set
  - own tasks only     -> private to that user
Valid only while the data fingerprint is unchanged and younger than AI_CACHE_TTL_MIN."""
import hashlib
import re
from datetime import timedelta
from typing import Optional

from auth import User
from config import AI_CACHE_TTL_MIN
from database import get_conn
from utils import now_utc, to_iso, parse_dt

FILLER = {"please", "pls", "plz", "kindly", "can", "could", "you", "tell", "me", "show", "give", "list", "batao",
          "bata", "do", "dikhao", "mujhe", "mera", "meri", "mere", "my", "the", "a", "an", "of", "all", "kya", "hai",
          "hain", "are", "is", "what", "which", "ke", "ka", "ki", "now", "currently", "right", "abhi", "jo", "that",
          "and", "aur", "to", "for", "in", "about", "hi", "ko", "se"}


def normalize(question: str) -> str:
    words = re.findall(r"[a-z0-9#%]+", (question or "").lower())
    return " ".join(sorted({w for w in words if w not in FILLER}))


def scope_of(user: User) -> str:
    if user.sees_all_tasks:
        return "perm:" + hashlib.sha1(",".join(sorted(user.permissions)).encode()).hexdigest()[:12]
    return f"user:{user.id}"


def data_version(user: User) -> str:
    where, params = ("", ()) if user.sees_all_tasks else (" WHERE assigned_to=?", (user.id,))
    with get_conn() as conn:
        t = conn.execute(f"SELECT COUNT(*), IFNULL(MAX(updated_at),''), IFNULL(SUM(progress),0), IFNULL(MAX(id),0) FROM tasks{where}", params).fetchone()
        u = conn.execute("SELECT COUNT(*), IFNULL(SUM(token_version),0), IFNULL(GROUP_CONCAT(display_name),'') FROM users WHERE is_active=1").fetchone()
        a = conn.execute("SELECT IFNULL(MAX(id),0) FROM audit_log").fetchone()
    raw = f"{tuple(t)}|{tuple(u)}|{a[0] if user.has('audit.view') else ''}|{now_utc().strftime('%Y%m%d%H')}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def get(user: User, question: str) -> Optional[dict]:
    key = normalize(question)
    if not key:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_cache WHERE scope=? AND qkey=?", (scope_of(user), key)).fetchone()
        if not row:
            return None
        fresh = parse_dt(row["created_at"]) > now_utc() - timedelta(minutes=AI_CACHE_TTL_MIN)
        if not fresh or row["data_version"] != data_version(user):
            conn.execute("DELETE FROM ai_cache WHERE scope=? AND qkey=?", (scope_of(user), key))
            return None
        conn.execute("UPDATE ai_cache SET hits = hits + 1 WHERE scope=? AND qkey=?", (scope_of(user), key))
    return {"answer": row["answer"], "tokens_saved": row["tokens"]}


def put(user: User, question: str, answer: str, tokens: int) -> None:
    key = normalize(question)
    if not key or not answer:
        return
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO ai_cache(scope, qkey, question, answer, data_version, tokens, hits, created_at) "
                     "VALUES (?,?,?,?,?,?,0,?)", (scope_of(user), key, question[:300], answer, data_version(user), int(tokens or 0), to_iso(now_utc())))
        conn.execute("DELETE FROM ai_cache WHERE created_at < ?", (to_iso(now_utc() - timedelta(minutes=AI_CACHE_TTL_MIN * 4)),))


def clear(user: User = None) -> None:
    with get_conn() as conn:
        if user is None:
            conn.execute("DELETE FROM ai_cache")
        else:
            conn.execute("DELETE FROM ai_cache WHERE scope=?", (scope_of(user),))
