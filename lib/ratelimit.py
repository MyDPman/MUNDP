"""Simple in-memory login rate-limiter.

Tracks failed attempts per (username, remote_ip) pair. After ``MAX_ATTEMPTS``
failures within ``WINDOW_SECONDS``, further attempts are rejected for
``LOCKOUT_SECONDS``.

In-memory means it resets when the process restarts and doesn't share state
across worker processes. That's fine for a single-gunicorn-worker LAN deploy.
For multi-worker or multi-host, swap the dict for Redis.
"""
import threading
import time
from collections import deque
from typing import Optional

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60   # 15 minutes
LOCKOUT_SECONDS = 15 * 60  # 15 minutes

_lock = threading.Lock()
_attempts: dict[tuple[str, str], deque[float]] = {}
_lockouts: dict[tuple[str, str], float] = {}


def _key(username: str, ip: str) -> tuple[str, str]:
    return (username.strip().lower(), ip or "unknown")


def check_login_rate_limit(username: str, ip: str) -> Optional[int]:
    """Return seconds remaining on a lockout, or None if not locked out."""
    key = _key(username, ip)
    now = time.time()
    with _lock:
        until = _lockouts.get(key)
        if until and until > now:
            return int(until - now)
        if until and until <= now:
            _lockouts.pop(key, None)
    return None


def record_login_attempt(username: str, ip: str, *, success: bool) -> None:
    key = _key(username, ip)
    now = time.time()
    with _lock:
        if success:
            _attempts.pop(key, None)
            _lockouts.pop(key, None)
            return
        dq = _attempts.setdefault(key, deque())
        dq.append(now)
        while dq and now - dq[0] > WINDOW_SECONDS:
            dq.popleft()
        if len(dq) >= MAX_ATTEMPTS:
            _lockouts[key] = now + LOCKOUT_SECONDS
            dq.clear()
