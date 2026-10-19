"""Minimal JWT (HS256) implementation using only the Python standard library.
Token = base64url(header) . base64url(payload) . base64url(HMAC-SHA256 signature)
Claims: sub (user id), role, name, tv (token version), jti (token id), iat, exp, iss."""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from config import JWT_SECRET, JWT_ALGORITHM, JWT_ISSUER, TOKEN_HOURS
from errors import Unauthorized
from utils import now_utc


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(signing_input: str) -> str:
    return _b64e(hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest())


def encode(claims: dict) -> tuple:
    now = int(now_utc().timestamp())
    payload = {**claims, "iss": JWT_ISSUER, "iat": now,
               "exp": now + int(timedelta(hours=TOKEN_HOURS).total_seconds()), "jti": secrets.token_urlsafe(12)}
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    signing_input = (_b64e(json.dumps(header, separators=(",", ":")).encode()) + "." +
                     _b64e(json.dumps(payload, separators=(",", ":")).encode()))
    return f"{signing_input}.{_sign(signing_input)}", payload


def decode(token: str) -> dict:
    """Verify signature, algorithm, issuer and expiry. Raises Unauthorized on any problem."""
    try:
        h64, p64, s64 = token.split(".")
        header = json.loads(_b64d(h64))
        payload = json.loads(_b64d(p64))
    except (ValueError, json.JSONDecodeError):
        raise Unauthorized("Invalid token. Please log in again.")
    if header.get("alg") != JWT_ALGORITHM or not hmac.compare_digest(_sign(f"{h64}.{p64}"), s64) \
            or payload.get("iss") != JWT_ISSUER:
        raise Unauthorized("Invalid token. Please log in again.")
    if int(payload.get("exp", 0)) < int(now_utc().timestamp()):
        raise Unauthorized("Session expired. Please log in again.")
    return payload
