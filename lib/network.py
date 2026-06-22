import os

from flask import abort, request


def _allowed_prefixes() -> list[str]:
    raw = os.environ.get("ALLOWED_IP_PREFIXES", "127.0.0.1,::1")
    return [p.strip() for p in raw.split(",") if p.strip()]


def enforce_network_allowlist() -> None:
    """Reject any request whose source IP doesn't match a configured prefix.

    Configure via ALLOWED_IP_PREFIXES env var. Defaults to localhost only.
    Trust the direct peer address — do NOT trust X-Forwarded-For unless this
    app is behind a reverse proxy you control.
    """
    remote = request.remote_addr or ""
    prefixes = _allowed_prefixes()
    if not any(remote.startswith(p) for p in prefixes):
        abort(403, description=f"Access denied for IP {remote}")
