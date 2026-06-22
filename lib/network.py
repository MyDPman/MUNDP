import os

from flask import abort, request


def _allowed_prefixes() -> list[str]:
    raw = os.environ.get("ALLOWED_IP_PREFIXES", "127.0.0.1,::1")
    return [p.strip() for p in raw.split(",") if p.strip()]


def enforce_network_allowlist() -> None:
    """Reject any request whose source IP doesn't match a configured prefix.

    Configure via ALLOWED_IP_PREFIXES env var. Defaults to localhost only.
    Set ALLOWED_IP_PREFIXES=* to allow all IPs (use behind a trusted proxy).
    """
    raw = os.environ.get("ALLOWED_IP_PREFIXES", "127.0.0.1,::1")
    if raw.strip() == "*":
        return
    remote = request.remote_addr or ""
    prefixes = [p.strip() for p in raw.split(",") if p.strip()]
    if not any(remote.startswith(p) for p in prefixes):
        abort(403, description=f"Access denied for IP {remote}")
