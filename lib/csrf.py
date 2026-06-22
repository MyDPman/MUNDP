"""Synchronizer-token CSRF protection.

The token is stored in Flask's signed session cookie. HTML forms include it as a
hidden ``csrf_token`` field; JSON requests pass it in the ``X-CSRF-Token`` header.
"""
import hmac
import secrets

from flask import abort, request, session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SESSION_KEY = "_csrf_token"


def get_csrf_token() -> str:
    token = session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[SESSION_KEY] = token
        session.permanent = True
    return token


def _submitted_token() -> str:
    header = request.headers.get("X-CSRF-Token")
    if header:
        return header
    if request.is_json:
        data = request.get_json(silent=True) or {}
        return data.get("csrf_token") or ""
    return request.form.get("csrf_token") or ""


def verify_csrf() -> None:
    if request.method in SAFE_METHODS:
        return
    expected = session.get(SESSION_KEY) or ""
    submitted = _submitted_token()
    if not expected or not submitted or not hmac.compare_digest(expected, submitted):
        abort(400, description="Invalid or missing CSRF token. Reload and try again.")
