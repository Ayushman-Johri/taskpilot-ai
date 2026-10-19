"""Date/time and small helpers. All timestamps are stored in UTC ISO-8601."""
import re
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from config import LOCAL_TZ
from errors import BadRequest


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: str) -> datetime:
    """Parse ISO datetime; naive values are treated as local time (APP_TZ). Date only -> 18:00."""
    if not value or not isinstance(value, str):
        raise BadRequest("Deadline is required (format: YYYY-MM-DDTHH:MM).")
    v = value.strip().replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        v += "T18:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise BadRequest(f"Invalid date/time '{value}'. Use format YYYY-MM-DDTHH:MM.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc)


def fmt_local(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    return parse_dt(iso).astimezone(LOCAL_TZ).strftime("%d %b %Y, %I:%M %p")


def fmt_short(iso: Optional[str]) -> Optional[str]:
    """Compact local time for AI data rows, e.g. '18 Oct 18:00'."""
    if not iso:
        return None
    return parse_dt(iso).astimezone(LOCAL_TZ).strftime("%d %b %H:%M")


def local_input_value(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    return parse_dt(iso).astimezone(LOCAL_TZ).strftime("%Y-%m-%dT%H:%M")


def humanize_remaining(seconds: float) -> str:
    s = abs(int(seconds))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    text = f"{d}d {h}h" if d else f"{h}h {m}m" if h else f"{m}m"
    return f"Overdue by {text}" if seconds < 0 else f"{text} left"


def generate_password(length: int = 10) -> str:
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0OoIl1")
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in pwd) and any(c.isalpha() for c in pwd):
            return pwd


def slugify_username(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return slug[:30] or "user"
