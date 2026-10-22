"""Password hashing, JWT login/logout and permission checks.

Every request: JWT signature + expiry  ->  user active, token_version and role_id still match
->  permissions are LOADED FROM THE DATABASE (role_permissions). Editing a role's permissions
therefore takes effect on the very next request, without logging anyone out."""
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Optional, Tuple

from flask import g, request

import jwt_utils
from database import get_conn, audit, role_permissions
from errors import Unauthorized, Forbidden
from permissions import WRITE_PERMS
from utils import now_utc, to_iso


@dataclass
class User:
    id: int
    username: str
    display_name: str
    role_id: int
    role_name: str
    permissions: frozenset = field(default_factory=frozenset)

    def has(self, *perms) -> bool:
        return all(p in self.permissions for p in perms)

    def has_any(self, *perms) -> bool:
        return any(p in self.permissions for p in perms)

    @property
    def sees_all_tasks(self) -> bool:
        return "tasks.view_all" in self.permissions

    @property
    def can_write(self) -> bool:
        return bool(self.permissions & WRITE_PERMS)

    def to_dict(self) -> dict:
        return {"id": self.id, "username": self.username, "display_name": self.display_name,
                "role_id": self.role_id, "role": self.role_name, "permissions": sorted(self.permissions)}


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex(), salt


def load_user(conn, user_id: int) -> Optional[User]:
    row = conn.execute("""SELECT u.id, u.username, u.display_name, u.role_id, u.token_version, r.name AS role_name
                          FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id=? AND u.is_active=1""",
                       (user_id,)).fetchone()
    if not row:
        return None
    user = User(row["id"], row["username"], row["display_name"], row["role_id"], row["role_name"],
                frozenset(role_permissions(conn, row["role_id"])))
    user._token_version = row["token_version"]
    return user


def login(username: str, password: str):
    username = (username or "").strip().lower()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()
        if not row or not secrets.compare_digest(hash_password(password or "", row["salt"])[0], row["password_hash"]):
            audit(None, "login_failed", username)
            raise Unauthorized("Invalid username or password.")
        user = load_user(conn, row["id"])
    token, payload = jwt_utils.encode({"sub": str(user.id), "rid": user.role_id, "tv": row["token_version"]})
    audit(user.id, "login", user.role_name)
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
        user = load_user(conn, int(payload.get("sub", 0)))
        revoked = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti=?", (payload.get("jti"),)).fetchone()
    if not user or revoked or user._token_version != payload.get("tv") or user.role_id != payload.get("rid"):
        raise Unauthorized("Session expired. Please log in again.")
    return user


def require(*perms, any_of: bool = False):
    """@require()                        -> any logged-in user
       @require("tasks.create")          -> must have the permission
       @require("a", "b", any_of=True)   -> must have at least one"""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = _bearer_token()
            user = user_from_token(token)
            ok = (not perms) or (user.has_any(*perms) if any_of else user.has(*perms))
            if not ok:
                audit(user.id, "access_denied", f"{request.method} {request.path}")
                raise Forbidden("You don't have permission to do this.")
            g.user, g.token = user, token
            return fn(*args, **kwargs)
        return wrapper
    return decorator
