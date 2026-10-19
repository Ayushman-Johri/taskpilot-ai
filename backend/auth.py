"""Password hashing, JWT login/logout and role-based route decorators.
1. Client sends  Authorization: Bearer <JWT>
2. jwt_utils.decode() checks signature + expiry
3. Small DB check: user active, token_version matches (password reset / role change / delete
   bump it -> old tokens die instantly), jti not revoked (logout)."""
import hashlib
import secrets
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from functools import wraps
from typing import Optional, Tuple

from flask import g, request

import jwt_utils
from database import get_conn, audit
from errors import Unauthorized, Forbidden
from utils import now_utc, to_iso


@dataclass
class User:
    id: int
    username: str
    display_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_agent(self) -> bool:
        return self.role == "agent"

    def to_dict(self) -> dict:
        return asdict(self)


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex(), salt


def login(username: str, password: str):
    username = (username or "").strip().lower()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
    if not row or not secrets.compare_digest(hash_password(password or "", row["salt"])[0], row["password_hash"]):
        audit(None, "login_failed", username)
        raise Unauthorized("Invalid username or password.")
    user = User(row["id"], row["username"], row["display_name"], row["role"])
    token, payload = jwt_utils.encode({"sub": str(user.id), "role": user.role, "name": user.display_name,
                                       "tv": row["token_version"]})
    audit(user.id, "login", user.role)
    return token, user, payload["exp"]


def logout(token: str) -> None:
    payload = jwt_utils.decode(token)
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    with get_conn() as conn:
        conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (to_iso(now_utc()),))
        conn.execute("INSERT OR IGNORE INTO revoked_tokens(jti, expires_at) VALUES (?,?)", (payload["jti"], to_iso(exp)))


def revoke_all_tokens(conn, user_id: int) -> None:
    conn.execute("UPDATE users SET token_version = token_version + 1 WHERE id=?", (user_id,))


def _bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized("Please log in.")
    return header.split(" ", 1)[1].strip()


def user_from_token(token: str) -> User:
    payload = jwt_utils.decode(token)
    with get_conn() as conn:
        row = conn.execute("SELECT id, username, display_name, role, token_version FROM users "
                           "WHERE id=? AND is_active=1", (int(payload.get("sub", 0)),)).fetchone()
        revoked = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti=?", (payload.get("jti"),)).fetchone()
    if not row or revoked or row["token_version"] != payload.get("tv") or row["role"] != payload.get("role"):
        raise Unauthorized("Session expired. Please log in again.")
    return User(row["id"], row["username"], row["display_name"], row["role"])


def require_role(*roles: str):
    """@require_role() -> any logged-in user; @require_role("admin") -> admins only."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = _bearer_token()
            user = user_from_token(token)
            if roles and user.role not in roles:
                audit(user.id, "access_denied", f"{request.method} {request.path}")
                raise Forbidden("You are not authorized to perform this action.")
            g.user, g.token = user, token
            return fn(*args, **kwargs)
        return wrapper
    return decorator
