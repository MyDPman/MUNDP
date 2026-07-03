import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from flask import g, request

from .db import get_db

SESSION_COOKIE = "mundp_session"
SESSION_LIFETIME_DAYS = 7


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_LIFETIME_DAYS)
    db = get_db()
    db.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires.isoformat()),
    )
    db.commit()
    return token


def delete_session(token: str) -> None:
    db = get_db()
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    db.commit()


def purge_expired_sessions() -> None:
    db = get_db()
    db.execute(
        "DELETE FROM sessions WHERE expires_at < ?",
        (datetime.now(timezone.utc).isoformat(),),
    )
    db.commit()


def load_current_user() -> None:
    """Populate g.user from session cookie. Runs as a before_request hook."""
    g.user = None
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return
    db = get_db()
    row = db.execute(
        """
        SELECT u.id, u.username, u.display_name, u.role,
               u.committee, u.delegation, u.exec_role_id, s.expires_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        return
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        delete_session(token)
        return
    g.user = {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "committee": row["committee"],
        "delegation": row["delegation"],
        "exec_role_id": row["exec_role_id"],
    }
