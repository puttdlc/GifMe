"""Optional login: a signed, expiring session cookie set by a login page.

Turned on by setting both GIFME_USERNAME and GIFME_PASSWORD. The token is
`<expiry>.<hmac>`. The HMAC key mixes a random secret kept in the workdir (so
sessions survive restarts and container rebuilds) with the credentials (so
changing the password signs everyone out). Failed logins are rate limited per
client and globally, since the point of auth is an internet-facing deployment.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from jobs import WORK_DIR

USERNAME = os.environ.get("GIFME_USERNAME") or ""
PASSWORD = os.environ.get("GIFME_PASSWORD") or ""
ENABLED = bool(USERNAME and PASSWORD)

COOKIE = "gifme_session"
KEY_FILE = ".session-key"  # in WORK_DIR; clear_workdir() leaves it alone
SESSION_DAYS = 30
REFRESH_DAYS = 15          # re-issue the cookie once it has less than this left

WINDOW = 15 * 60           # failures counted over this many seconds
MAX_PER_CLIENT = 5
MAX_GLOBAL = 30            # caps guessing spread across many IPs

_failures: dict[str, list[float]] = {}


def _secret() -> bytes:
    path = WORK_DIR / KEY_FILE
    try:
        return path.read_bytes()
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        return key


_KEY = hmac.new(_secret(), f"{USERNAME}\0{PASSWORD}".encode(), hashlib.sha256).digest() if ENABLED else b""


def _sign(expiry: int) -> str:
    return hmac.new(_KEY, str(expiry).encode(), hashlib.sha256).hexdigest()


def issue() -> tuple[str, int]:
    """A new token and its max-age in seconds."""
    max_age = SESSION_DAYS * 86400
    expiry = int(time.time()) + max_age
    return f"{expiry}.{_sign(expiry)}", max_age


def check(token: str | None) -> int:
    """Seconds left on a valid token, else 0."""
    if not token:
        return 0
    expiry, _, sig = token.partition(".")
    if not expiry.isdigit() or not hmac.compare_digest(sig, _sign(int(expiry))):
        return 0
    return max(0, int(expiry) - int(time.time()))


def needs_refresh(left: int) -> bool:
    return left < REFRESH_DAYS * 86400


def credentials_ok(user: str, pw: str) -> bool:
    return secrets.compare_digest(user.encode(), USERNAME.encode()) & secrets.compare_digest(pw.encode(), PASSWORD.encode())


def _recent(key: str, now: float) -> list[float]:
    hits = [t for t in _failures.get(key, []) if now - t < WINDOW]
    if hits:
        _failures[key] = hits
    else:
        _failures.pop(key, None)
    return hits


def locked_for(client: str) -> int:
    """Seconds until this client may try again, or 0."""
    now = time.time()
    waits = [WINDOW - (now - hits[0]) for key, limit in ((client, MAX_PER_CLIENT), ("*", MAX_GLOBAL))
             if len(hits := _recent(key, now)) >= limit]
    return int(max(waits)) + 1 if waits else 0


def record_failure(client: str) -> None:
    now = time.time()
    if len(_failures) > 5000:  # drop stale clients so the map can't grow forever
        for key in list(_failures):
            _recent(key, now)
    for key in (client, "*"):
        _failures.setdefault(key, []).append(now)


def clear_failures(client: str) -> None:
    _failures.pop(client, None)
