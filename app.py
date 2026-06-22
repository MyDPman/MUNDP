import csv
import io
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for,
)
from werkzeug.utils import secure_filename

from lib.auth import (
    SESSION_COOKIE, create_session, delete_session, hash_password,
    load_current_user, verify_password,
)
from lib.countries import COUNTRY_ISO3, iso3 as country_iso3
from lib.csrf import get_csrf_token, verify_csrf
from lib.db import close_db, get_db, init_db
from lib.decorators import admin_required, login_required, roles_required
from lib.network import enforce_network_allowlist
from lib.ratelimit import check_login_rate_limit, record_login_attempt

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or os.path.join(BASE_DIR, "uploads")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))

# Committees for the International Summit section.
_DEF_COMS = ["UNIDO", "UNHCR", "OHCHR", "UNDPPA", "UNESCO"]
VALID_ROLES = ("admin", "chair", "delegate", "advisor", "exec_gc")

# Pages EXEC/GC users may visit. Anything else returns 403.
EXEC_GC_ALLOWED_PREFIXES = (
    "/schedule", "/tally", "/help", "/settings",
    "/static/", "/api/badges", "/logout", "/login", "/impersonate/stop",
    "/summit", "/my-committee", "/admin/config",
)

# Schools that may have advisors at the conference. Maps full school name
# (as shown in the dropdown) to the short code used in usernames and display
# names — e.g. {"Koç School": "KOC"} → adv-koc / "ADV - KOC".
# Add entries here as schools register.
_DEF_SCHLS = {
    # "Koç School": "KOC",
}

_DEF_SEC_EMAIL = "secretariat@modelundp.org"
_DEF_EXT_URL = "https://modelundp.org"

VALID_DOC_STATUSES = ("pending", "debated", "passed", "failed")

# Conference local timezone (GMT+3, Türkiye — no DST since 2016)
LOCAL_TZ = timezone(timedelta(hours=3))

import re as _re
_GOOGLE_DOC_RE = _re.compile(
    r"^https://docs\.google\.com/document/d/([A-Za-z0-9_-]+)"
)


def _google_doc_id(url):
    if not url:
        return None
    m = _GOOGLE_DOC_RE.match(url.strip())
    return m.group(1) if m else None


def _normalize_google_doc_url(url):
    """Return a canonical share URL (just the doc edit page) or None if invalid."""
    doc_id = _google_doc_id(url)
    if not doc_id:
        return None
    return f"https://docs.google.com/document/d/{doc_id}/edit"

# Tally Tracker — points per action
TALLY_POINTS = {"poi": 1, "speech": 2, "amendment": 2}
TALLY_LABELS = {"poi": "POI", "speech": "Speech", "amendment": "Amendment"}

# Committee leadership and agenda items.
# Sourced from https://modelundp.org/committee/<name>
_DEF_COM_INFO = {
    "UNIDO": {
        "president": "Damla Çakır",
        "deputy_presidents": ["Ada Keskin", "Ömer Emin Özkan"],
        "agenda_items": [
            "Strengthening Industrial Infrastructure and Energy Resilience in Samoa",
            "Curbing the Setback of Indonesia's Manufacturing Sector",
            "Facilitating the Transition From Fossil Fuels to Diversified Industrial Development in Brunei",
        ],
    },
    "UNHCR": {
        "president": "Doruk Ege Özgülşen",
        "deputy_presidents": ["Mete Cem Utku", "Ahmet Hasan Yurtçu"],
        "agenda_items": [
            "Tackling the Maltreatment of Asylum Seekers in Malaysia",
            "Addressing the Impact of the Rohingya Refugee Crisis on Bangladesh",
            "Reducing the Impact of Violence on Displaced Populations Resulting from the West Papua Conflict",
        ],
    },
    "OHCHR": {
        "president": "Bahri Çağrı Toygar",
        "deputy_presidents": ["Derin Halatçı", "Beren Yasemin Aydıner"],
        "agenda_items": [
            "Promoting Freedom of Expression in the Philippines",
            "Protecting the Rights of Displaced Domestic Workers in Post-Coup Myanmar",
            "Upholding Human Rights Principles in China's Xinjiang Region",
        ],
    },
    "UNDPPA": {
        "president": "Sanem Naz Kafalı",
        "deputy_presidents": ["Berke Ballıel", "Zeynep Duru Görmeli"],
        "agenda_items": [
            "Mediating the Sovereignty Dispute in the Spratly Islands",
            "Facilitating Post-Conflict Reconciliation in the Philippines' Bangsamoro Region",
            "Assessing the Expansion of State Surveillance in Hong Kong",
        ],
    },
    "UNESCO": {
        "president": "Can Kuzey Güner",
        "deputy_presidents": ["Defne Erdoğan", "Elif Galiba"],
        "agenda_items": [
            "Upholding the Cultural Heritage of Nomadic Communities in Mongolia",
            "Improving Equitable Access to Education in Pacific Island Nations",
            "Preventing the Politicization of Cultural Sites in Contested East Asian Territories",
        ],
    },
}


# Conference schedule — sourced from https://modelundp.org/schedule
_DEF_SCHED = [
    {
        "day": "Friday, 22 May 2026",
        "items": [
            ("09:30 – 10:00", "Buses arrive"),
            ("10:00 – 10:15", "StOFF Briefing"),
            ("10:00 – 11:00", "Welcome Coffee"),
            ("11:00 – 12:00", "Opening Ceremony"),
            ("12:00 – 12:15", "Coffee break"),
            ("12:15 – 13:30", "Committee sessions begin"),
            ("13:30 – 14:30", "Lunch break"),
            ("14:30 – 16:00", "Continued committee work"),
            ("16:00 – 16:15", "Coffee break"),
            ("16:15 – 17:30", "Final committee session"),
            ("17:30 – 17:45", "StOFF Debriefing"),
            ("17:45 – 18:00", "Buses depart"),
        ],
    },
    {
        "day": "Saturday, 23 May 2026",
        "items": [
            ("08:00 – 08:30", "Buses arrive"),
            ("08:45 – 09:00", "Staff briefing"),
            ("09:00 – 10:30", "Committee sessions"),
            ("10:30 – 10:45", "Coffee break"),
            ("10:45 – 12:15", "Continued sessions"),
            ("12:15 – 13:15", "Lunch break"),
            ("13:15 – 14:30", "Committee work"),
            ("14:30 – 14:45", "Coffee break"),
            ("14:45 – 16:15", "Sessions continue"),
            ("16:15 – 16:30", "Coffee break"),
            ("16:30 – 17:30", "Final committee session"),
            ("17:30 – 17:45", "Staff debriefing"),
            ("17:45 – 18:00", "Buses depart"),
        ],
    },
    {
        "day": "Sunday, 24 May 2026",
        "items": [
            ("08:00 – 08:30", "Buses arrive"),
            ("08:45 – 09:00", "Staff briefing"),
            ("09:00 – 11:00", "Committee sessions"),
            ("11:00 – 11:15", "Coffee break"),
            ("11:15 – 13:00", "International Summit and APQ sessions"),
            ("13:00 – 14:00", "Lunch break"),
            ("14:00 – 15:45", "APQ and Summit continue"),
            ("15:45 – 16:00", "Coffee break"),
            ("16:00 – 17:15", "Closing Ceremony"),
            ("17:15 – 17:30", "Buses depart"),
        ],
    },
]
_DEF_CONF_LOC = "The Koç School, Istanbul"


# ---------------------------------------------------------------------------
# Dynamic admin-editable configuration. Values live in the `app_config` table
# as a single JSON row. On first read we seed it with the code defaults above
# so existing installs keep working. All places that previously imported the
# constants should call _cfg("...") instead.
# ---------------------------------------------------------------------------
import json as _json

def _default_config() -> dict:
    # All collections start empty so a fresh install has zero opinions about
    # committees / schools / schedule — the admin fills them in via the
    # Configurations page. Conference text fields and the upload window keep
    # sensible defaults that the admin can still overwrite.
    return {
        "schools": {},
        "committees": [],
        "conference": {
            "location": _DEF_CONF_LOC,
            "secretariat_email": _DEF_SEC_EMAIL,
            "external_website_url": _DEF_EXT_URL,
        },
        "upload_permission_minutes": _DEF_UPL_MIN,
        "schedule": [],
    }


def _load_config() -> dict:
    """Read the current dynamic config from the DB; seed defaults on first use."""
    if hasattr(g, "_app_config"):
        return g._app_config
    row = get_db().execute("SELECT data FROM app_config WHERE id = 1").fetchone()
    if row:
        try:
            cfg = _json.loads(row["data"])
        except (ValueError, TypeError):
            cfg = _default_config()
    else:
        cfg = _default_config()
        _store_config(cfg)
    g._app_config = cfg
    return cfg


def _store_config(cfg: dict) -> None:
    db = get_db()
    user_id = g.user["id"] if getattr(g, "user", None) else None
    db.execute(
        "INSERT INTO app_config (id, data, updated_at, updated_by) "
        "VALUES (1, ?, datetime('now'), ?) "
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data, "
        "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (_json.dumps(cfg), user_id),
    )
    db.commit()
    g._app_config = cfg


def _cfg_committees() -> list:
    return [c["code"] for c in _load_config().get("committees", [])]


def _cfg_committee_info() -> dict:
    """Return a dict shaped like the legacy _cfg_committee_info() using the live
    config for agenda items, but leaving president/deputy_president display
    strings as they are in code (those are display-only and will be
    superseded by the actual chair-user records when rendering)."""
    out = {}
    for c in _load_config().get("committees", []):
        code = c["code"]
        out[code] = {
            "president": (_DEF_COM_INFO.get(code, {}) or {}).get("president", ""),
            "deputy_presidents": (_DEF_COM_INFO.get(code, {}) or {}).get("deputy_presidents", []),
            "agenda_items": list(c.get("agenda_items", [])),
        }
    return out


def _cfg_schools() -> dict:
    return dict(_load_config().get("schools", {}))


def _cfg_conference() -> dict:
    return dict(_load_config().get("conference", {}))


def _cfg_upload_minutes() -> int:
    try:
        return int(_load_config().get("upload_permission_minutes", _DEF_UPL_MIN))
    except (TypeError, ValueError):
        return _DEF_UPL_MIN


def _cfg_schedule() -> list:
    raw = _load_config().get("schedule", [])
    return [
        {"day": d.get("day", ""), "items": [tuple(it) if len(it) == 2 else (it[0], "") for it in d.get("items", [])]}
        for d in raw
    ]


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)
init_db()

app.teardown_appcontext(close_db)


@app.before_request
def before_request():
    enforce_network_allowlist()
    load_current_user()
    if request.endpoint != "setup":
        verify_csrf()
    # EXEC/GC users are restricted to a small set of pages — everything else
    # 403s. The redirect from "/" to "/schedule" is handled in index().
    user = getattr(g, "user", None)
    if user and user.get("role") == "exec_gc":
        path = request.path or "/"
        if path != "/" and not any(path.startswith(p) for p in EXEC_GC_ALLOWED_PREFIXES):
            abort(403)


@app.template_filter("local")
def _local_time(value, fmt="%Y-%m-%d %H:%M"):
    """Convert a UTC ISO/SQL timestamp string to Istanbul-time formatted string."""
    if not value:
        return ""
    s = str(value).strip()
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "").split(".")[0])
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).strftime(fmt)


@app.template_filter("local_short")
def _local_short(value):
    return _local_time(value, "%d %b %H:%M")


@app.template_filter("local_date")
def _local_date(value):
    return _local_time(value, "%Y-%m-%d")


@app.template_filter("local_time_only")
def _local_time_only(value):
    return _local_time(value, "%H:%M")


@app.context_processor
def inject_user():
    impersonator = None
    if session.get("impersonator_token"):
        impersonator = {
            "name": session.get("impersonator_name"),
            "id": session.get("impersonator_id"),
        }
    return {
        "current_user": getattr(g, "user", None),
        "csrf_token": get_csrf_token,
        "external_website_url": _cfg_conference().get("external_website_url", ""),
        "secretariat_email": _cfg_conference().get("secretariat_email", ""),
        "badges": _compute_badges(),
        "impersonator": impersonator,
    }


def _doc_visibility_clause(prefix="d"):
    """Return (SQL fragment, params) restricting a documents query to rows the
    current user is allowed to see.

    Rules:
      * Admin: everything.
      * Chair: every approved doc + their own committee (including pending
        approval) + anything they personally uploaded.
      * Delegate: own uploads always. Otherwise must be approved AND either
        in their own committee OR no longer pending — i.e. delegates from
        other committees can only see resolutions once they've been debated.
      * Anonymous (shouldn't reach here): approved only.
    """
    user = getattr(g, "user", None)
    if not user:
        return f"{prefix}.approved = 1", []
    if user["role"] == "admin":
        return "1 = 1", []
    if user["role"] == "chair":
        committee = (user.get("committee") or "").strip()
        return (
            f"({prefix}.approved = 1 OR {prefix}.uploader_id = ? OR {prefix}.committee = ?)",
            [user["id"], committee],
        )
    # delegate — sees all approved docs in the list, plus own uploads
    return (
        f"({prefix}.uploader_id = ? OR {prefix}.approved = 1)",
        [user["id"]],
    )


def _wants_json() -> bool:
    """Return True if the request prefers a JSON response (XHR/fetch)."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept


# Permission-based upload window granted by chairs.
_DEF_UPL_MIN = 10


def _upload_permission_until(user_id: int):
    """Return the upload-permission expiry as a tz-aware datetime if still in
    the future, else None. Reads fresh from DB (g.user doesn't carry it)."""
    row = get_db().execute(
        "SELECT upload_permission_until FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row or not row["upload_permission_until"]:
        return None
    try:
        dt = datetime.fromisoformat(row["upload_permission_until"])
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt <= datetime.now(timezone.utc):
        return None
    return dt


def _user_can_upload(user) -> bool:
    """Admin & chair always; delegate only with an active permission window."""
    if not user:
        return False
    role = user.get("role")
    if role in ("admin", "chair"):
        return True
    if role == "delegate":
        return _upload_permission_until(user["id"]) is not None
    return False


def _mark_seen(field: str) -> None:
    """Update one of the *_last_seen_at columns on the current user to now."""
    user = getattr(g, "user", None)
    if not user:
        return
    if field not in ("notes_last_seen_at", "amendments_last_seen_at", "resolutions_last_seen_at"):
        return
    db = get_db()
    db.execute(f"UPDATE users SET {field} = datetime('now') WHERE id = ?", (user["id"],))
    db.commit()


def _compute_badges() -> dict:
    """Return {notes: n, amendments: n, resolutions: n} for the current user."""
    badges = {"notes": 0, "amendments": 0, "resolutions": 0}
    user = getattr(g, "user", None)
    if not user:
        return badges
    db = get_db()
    row = db.execute(
        """
        SELECT notes_last_seen_at, amendments_last_seen_at, resolutions_last_seen_at
        FROM users WHERE id = ?
        """,
        (user["id"],),
    ).fetchone()
    if not row:
        return badges
    EPOCH = "1970-01-01 00:00:00"
    notes_cut = row["notes_last_seen_at"] or EPOCH
    amend_cut = row["amendments_last_seen_at"] or EPOCH
    res_cut   = row["resolutions_last_seen_at"] or EPOCH
    role = user["role"]
    committee = user.get("committee")
    delegation = user.get("delegation")

    # Notes badge
    if role == "admin":
        badges["notes"] = db.execute(
            "SELECT COUNT(*) FROM notes WHERE created_at > ? AND sender_id != ?",
            (notes_cut, user["id"]),
        ).fetchone()[0]
    elif role == "chair" and committee:
        badges["notes"] = db.execute(
            "SELECT COUNT(*) FROM notes WHERE committee = ? AND created_at > ? AND sender_id != ?",
            (committee, notes_cut, user["id"]),
        ).fetchone()[0]
    elif committee and delegation:
        badges["notes"] = db.execute(
            """SELECT COUNT(*) FROM notes
               WHERE committee = ? AND recipient_delegation = ? AND created_at > ?""",
            (committee, delegation, notes_cut),
        ).fetchone()[0]

    # Amendments + Resolutions counts vary by role
    if role == "admin":
        badges["amendments"] = db.execute(
            "SELECT COUNT(*) FROM comments WHERE created_at > ? AND author_id != ?",
            (amend_cut, user["id"]),
        ).fetchone()[0]
        badges["resolutions"] = db.execute(
            "SELECT COUNT(*) FROM documents WHERE created_at > ? AND uploader_id != ?",
            (res_cut, user["id"]),
        ).fetchone()[0]
    elif role == "chair" and committee:
        badges["amendments"] = db.execute(
            """SELECT COUNT(*) FROM comments c
               JOIN documents d ON d.id = c.document_id
               WHERE d.committee = ? AND c.created_at > ? AND c.author_id != ?""",
            (committee, amend_cut, user["id"]),
        ).fetchone()[0]
        badges["resolutions"] = db.execute(
            """SELECT COUNT(*) FROM documents
               WHERE committee = ? AND created_at > ? AND uploader_id != ?""",
            (committee, res_cut, user["id"]),
        ).fetchone()[0]
    elif role == "delegate":
        # Delegates get a badge when one of their own resolutions is approved
        # by someone else since they last looked at the Resolutions tab.
        badges["resolutions"] = db.execute(
            """SELECT COUNT(*) FROM documents
               WHERE uploader_id = ?
                 AND approved = 1
                 AND approved_at IS NOT NULL
                 AND approved_at > ?
                 AND (approved_by IS NULL OR approved_by != ?)""",
            (user["id"], res_cut, user["id"]),
        ).fetchone()[0]
    return badges


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route("/setup", methods=["GET", "POST"])
def setup():
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] > 0:
        return redirect(url_for("login"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        display_name = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""
        if not username or not display_name or len(password) < 8:
            error = "All fields required; password min 8 chars."
        else:
            try:
                db.execute(
                    "INSERT INTO users (username, display_name, password_hash, role) VALUES (?, ?, ?, 'admin')",
                    (username, display_name, hash_password(password)),
                )
                db.commit()
                return redirect(url_for("login"))
            except Exception as e:
                error = str(e)
    return f"""<!doctype html><html><body style="font-family:sans-serif;max-width:400px;margin:80px auto;padding:20px">
    <h2>First-run setup</h2>
    {"<p style='color:red'>" + error + "</p>" if error else ""}
    <form method=post>
        <input type=hidden name=csrf_token value="">
        <p><input name=username placeholder=Username style="width:100%;padding:8px;box-sizing:border-box"></p>
        <p><input name=display_name placeholder="Display name" style="width:100%;padding:8px;box-sizing:border-box"></p>
        <p><input type=password name=password placeholder="Password (min 8 chars)" style="width:100%;padding:8px;box-sizing:border-box"></p>
        <button type=submit style="padding:10px 20px">Create admin</button>
    </form></body></html>"""


@app.route("/")
def index():
    user = getattr(g, "user", None)
    if user:
        if user.get("role") == "exec_gc":
            return redirect(url_for("schedule"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if getattr(g, "user", None):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        # The User Agreement must be accepted before any sign-in is processed.
        if not request.form.get("agree"):
            flash("You must accept the User Agreement to sign in.", "error")
            return render_template("login.html"), 400

        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        ip = request.remote_addr or "unknown"

        wait = check_login_rate_limit(username, ip)
        if wait is not None:
            minutes = (wait + 59) // 60
            flash(
                f"Too many failed attempts. Try again in {minutes} minute"
                f"{'s' if minutes != 1 else ''}.",
                "error",
            )
            return render_template("login.html"), 429

        db = get_db()
        row = db.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row and verify_password(password, row["password_hash"]):
            record_login_attempt(username, ip, success=True)
            token = create_session(row["id"])
            next_url = request.args.get("next") or url_for("dashboard")
            # Only allow relative redirects to prevent open-redirect via ?next=
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("dashboard")
            resp = redirect(next_url)
            resp.set_cookie(
                SESSION_COOKIE, token,
                httponly=True, samesite="Lax",
                max_age=7 * 24 * 3600,
            )
            return resp
        record_login_attempt(username, ip, success=False)
        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(token)
    # If signed in via admin impersonation, also drop the stashed admin session
    # so signing out clears everything rather than orphaning it.
    admin_token = session.pop("impersonator_token", None)
    session.pop("impersonator_name", None)
    session.pop("impersonator_id", None)
    if admin_token and admin_token != token:
        delete_session(admin_token)
    resp = redirect(url_for("login"))
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# Dashboard / document list
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    vis_sql, vis_params = _doc_visibility_clause("d")
    docs = db.execute(
        f"""
        SELECT d.id, d.title, d.description, d.filename, d.size_bytes,
               d.committee, d.created_at, d.approved, d.status, d.in_debate,
               d.uploader_id,
               u.display_name AS uploader_name,
               u.delegation   AS uploader_delegation,
               (SELECT COUNT(*) FROM comments c WHERE c.document_id = d.id) AS comment_count
        FROM documents d
        JOIN users u ON u.id = d.uploader_id
        WHERE {vis_sql}
        ORDER BY d.created_at DESC
        """,
        vis_params,
    ).fetchall()
    _mark_seen("resolutions_last_seen_at")
    return render_template("dashboard.html", documents=docs)


# ---------------------------------------------------------------------------
# International Summit (committee view)
# ---------------------------------------------------------------------------
@app.route("/summit")
@login_required
def summit():
    db = get_db()
    docs = db.execute(
        """
        SELECT d.id, d.title, d.description, d.committee, d.created_at,
               d.status, d.size_bytes, u.display_name AS uploader_name,
               (SELECT COUNT(*) FROM comments c WHERE c.document_id = d.id) AS comment_count
        FROM documents d
        JOIN users u ON u.id = d.uploader_id
        WHERE d.is_summit = 1 AND d.approved = 1
        ORDER BY d.committee
        """
    ).fetchall()
    by_committee = {c: None for c in _cfg_committees()}
    for d in docs:
        if d["committee"] in by_committee:
            by_committee[d["committee"]] = d
    return render_template(
        "summit.html",
        by_committee=by_committee,
        committees=_cfg_committees(),
        committee_info=_cfg_committee_info(),
    )


# ---------------------------------------------------------------------------
# Amendments overview (admin + chair) — grouped by committee
# ---------------------------------------------------------------------------
@app.route("/amendments")
@roles_required("chair")
def amendments_overview():
    db = get_db()
    rows = db.execute(
        """
        SELECT c.id, c.body, c.page_number, c.created_at, c.document_id,
               c.clause, c.sub_clause, c.sub_sub_clause,
               u.display_name AS author_name, u.role AS author_role,
               u.delegation   AS author_delegation,
               d.title AS document_title, d.committee
        FROM comments c
        JOIN users u ON u.id = c.author_id
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.created_at DESC
        """
    ).fetchall()
    by_committee = {c: [] for c in _cfg_committees()}
    for r in rows:
        if r["committee"] in by_committee:
            by_committee[r["committee"]].append(r)
    total = len(rows)
    _mark_seen("amendments_last_seen_at")
    return render_template(
        "amendments.html",
        by_committee=by_committee,
        committees=_cfg_committees(),
        total=total,
    )


# ---------------------------------------------------------------------------
# Tally Tracker — chair/admin only
# ---------------------------------------------------------------------------
@app.route("/tally", methods=["GET", "POST"])
@roles_required("chair", "advisor", "exec_gc")
def tally():
    db = get_db()
    user = g.user

    # EXEC/GC: see whatever the chair view would render, but read-only.
    if user["role"] == "exec_gc" and request.method == "POST":
        abort(403)

    # Advisor: render a separate read-only view organised by (country, committee).
    if user["role"] == "advisor":
        if request.method == "POST":
            abort(403)
        rows = db.execute(
            """SELECT a.country, a.committee
               FROM advisor_assignments a
               WHERE a.advisor_id = ?
               ORDER BY a.country, a.committee""",
            (user["id"],),
        ).fetchall()
        items = []
        for r in rows:
            country = r["country"]
            committee = r["committee"]
            # Lookup the delegate's participant name for this (committee, country),
            # if any. Blank if no delegate is assigned or no name is set.
            name_row = db.execute(
                """SELECT participant_name FROM users
                   WHERE role = 'delegate' AND committee = ? AND delegation = ?
                   ORDER BY id LIMIT 1""",
                (committee, country),
            ).fetchone()
            participant_name = (name_row["participant_name"] if name_row else "") or ""
            totals = _delegation_totals(db, committee, country)
            items.append({
                "country": country,
                "committee": committee,
                "participant_name": participant_name,
                "totals": totals,
            })
        return render_template(
            "advisor_tally.html",
            items=items,
            tally_labels=TALLY_LABELS,
        )

    if user["role"] == "admin":
        scope_committees = list(_cfg_committees())
    else:
        my_c = (user.get("committee") or "").strip()
        scope_committees = [my_c] if my_c in _cfg_committees() else []

    if request.method == "POST":
        committee = (request.form.get("committee") or "").strip()
        delegation = (request.form.get("delegation") or "").strip()
        kind = (request.form.get("kind") or "").strip()

        def fail(msg, code=400):
            if _wants_json():
                return jsonify({"ok": False, "error": msg}), code
            flash(msg, "error")
            return redirect(url_for("tally"))

        if committee not in scope_committees:
            return fail("Out of scope.", 403)
        if not delegation:
            return fail("Pick a delegation first.")
        if kind not in TALLY_POINTS:
            return fail("Invalid action.")

        cur = db.execute(
            """INSERT INTO tally_entries (committee, delegation, kind, points, recorded_by)
               VALUES (?, ?, ?, ?, ?)""",
            (committee, delegation, kind, TALLY_POINTS[kind], user["id"]),
        )
        entry_id = cur.lastrowid
        db.commit()

        if _wants_json():
            totals = _delegation_totals(db, committee, delegation)
            return jsonify({
                "ok": True,
                "delegation": delegation,
                "committee": committee,
                "totals": totals,
                "entry": {
                    "id": entry_id,
                    "committee": committee,
                    "delegation": delegation,
                    "kind": kind,
                    "points": TALLY_POINTS[kind],
                    "created_at": db.execute(
                        "SELECT created_at FROM tally_entries WHERE id = ?", (entry_id,)
                    ).fetchone()["created_at"],
                    "recorder_name": user["display_name"],
                    "label": TALLY_LABELS[kind],
                },
            })

        flash(
            f"+{TALLY_POINTS[kind]} {TALLY_LABELS[kind]} for {delegation} ({committee}).",
            "success",
        )
        return redirect(url_for("tally"))

    # Build per-committee data
    data = {}
    for c in scope_committees:
        delegations = set()
        for r in db.execute(
            """SELECT DISTINCT delegation FROM users
               WHERE committee = ? AND delegation IS NOT NULL AND delegation != ''""",
            (c,),
        ).fetchall():
            delegations.add(r["delegation"])
        for r in db.execute(
            "SELECT DISTINCT delegation FROM tally_entries WHERE committee = ?",
            (c,),
        ).fetchall():
            delegations.add(r["delegation"])

        rows = db.execute(
            """SELECT delegation, kind, COUNT(*) AS n, SUM(points) AS pts
               FROM tally_entries
               WHERE committee = ? AND reset_id IS NULL
               GROUP BY delegation, kind""",
            (c,),
        ).fetchall()
        tallies = {
            d: {"poi": 0, "speech": 0, "amendment": 0, "total": 0, "events": 0}
            for d in delegations
        }
        for r in rows:
            d = r["delegation"]
            if d not in tallies:
                tallies[d] = {"poi": 0, "speech": 0, "amendment": 0, "total": 0, "events": 0}
            tallies[d][r["kind"]] = r["n"]
            tallies[d]["total"] += r["pts"]
            tallies[d]["events"] += r["n"]
        ordered = sorted(tallies.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
        data[c] = ordered

    if scope_committees:
        placeholders = ",".join("?" * len(scope_committees))
        recent = db.execute(
            f"""SELECT t.id, t.committee, t.delegation, t.kind, t.points, t.created_at,
                       u.display_name AS recorder_name
                FROM tally_entries t
                JOIN users u ON u.id = t.recorded_by
                WHERE t.committee IN ({placeholders}) AND t.reset_id IS NULL
                ORDER BY t.created_at DESC LIMIT 30""",
            scope_committees,
        ).fetchall()
        # Pending reset events that can still be undone (i.e. still have at least
        # one entry tied to them — entries persist until DB row is deleted).
        recent_resets = db.execute(
            f"""SELECT r.id, r.committee, r.performed_at, r.entry_count,
                       u.display_name AS performer_name
                FROM tally_resets r
                LEFT JOIN users u ON u.id = r.performed_by
                WHERE r.committee IN ({placeholders})
                ORDER BY r.performed_at DESC LIMIT 10""",
            scope_committees,
        ).fetchall()
    else:
        recent = []
        recent_resets = []

    return render_template(
        "tally.html",
        data=data,
        recent=recent,
        recent_resets=recent_resets,
        scope_committees=scope_committees,
        tally_labels=TALLY_LABELS,
        tally_points=TALLY_POINTS,
    )


@app.route("/delegations/<int:user_id>/outside", methods=["POST"])
@roles_required("chair")
def toggle_outside(user_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, committee, outside_since, display_name FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        abort(404)
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        abort(403, description="You can only mark members of your own committee.")
    if row["outside_since"]:
        db.execute("UPDATE users SET outside_since = NULL WHERE id = ?", (user_id,))
        flash(f"{row['display_name']} is back in committee.", "success")
    else:
        db.execute(
            "UPDATE users SET outside_since = datetime('now') WHERE id = ?",
            (user_id,),
        )
        flash(f"{row['display_name']} marked as outside committee.", "success")
    db.commit()
    return redirect(url_for("my_committee"))


def _delegation_totals(db, committee: str, delegation: str) -> dict:
    """Return {poi, speech, amendment, total, events} counts for a delegation
    (only entries that haven't been zeroed-out by a reset)."""
    out = {"poi": 0, "speech": 0, "amendment": 0, "total": 0, "events": 0}
    for r in db.execute(
        """SELECT kind, COUNT(*) AS n, SUM(points) AS pts
           FROM tally_entries
           WHERE committee = ? AND delegation = ? AND reset_id IS NULL
           GROUP BY kind""",
        (committee, delegation),
    ).fetchall():
        out[r["kind"]] = r["n"]
        out["total"] += r["pts"]
        out["events"] += r["n"]
    return out


@app.route("/tally/reset", methods=["POST"])
@roles_required("chair")
def tally_reset():
    committee = (request.form.get("committee") or "").strip()
    db = get_db()
    if g.user["role"] != "admin" and committee != g.user.get("committee"):
        abort(403)
    if committee not in _cfg_committees():
        flash("Unknown committee.", "error")
        return redirect(url_for("tally"))
    # How many active entries do we have to archive?
    n = db.execute(
        "SELECT COUNT(*) FROM tally_entries WHERE committee = ? AND reset_id IS NULL",
        (committee,),
    ).fetchone()[0]
    if n == 0:
        flash(f"{committee} has no active entries to reset.", "error")
        return redirect(url_for("tally"))
    cur = db.execute(
        """INSERT INTO tally_resets (committee, performed_by, entry_count)
           VALUES (?, ?, ?)""",
        (committee, g.user["id"], n),
    )
    reset_id = cur.lastrowid
    db.execute(
        """UPDATE tally_entries SET reset_id = ?
           WHERE committee = ? AND reset_id IS NULL""",
        (reset_id, committee),
    )
    db.commit()
    flash(
        f"Reset {committee} tally — {n} entries archived. You can undo this below.",
        "success",
    )
    return redirect(url_for("tally"))


@app.route("/tally/reset/<int:reset_id>/undo", methods=["POST"])
@roles_required("chair")
def tally_reset_undo(reset_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, committee, entry_count FROM tally_resets WHERE id = ?",
        (reset_id,),
    ).fetchone()
    if not row:
        flash("Reset not found.", "error")
        return redirect(url_for("tally"))
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        abort(403)
    # Restore archived entries
    db.execute(
        "UPDATE tally_entries SET reset_id = NULL WHERE reset_id = ?",
        (reset_id,),
    )
    # Remove the reset event itself
    db.execute("DELETE FROM tally_resets WHERE id = ?", (reset_id,))
    db.commit()
    flash(
        f"Restored {row['entry_count']} entries to {row['committee']}.",
        "success",
    )
    return redirect(url_for("tally"))


@app.route("/tally/export.csv")
@roles_required("chair")
def tally_export_csv():
    """Download the tally as a CSV. Chairs get their own committee; admin gets all."""
    db = get_db()
    if g.user["role"] == "admin":
        scope = list(_cfg_committees())
    else:
        my_c = (g.user.get("committee") or "").strip()
        scope = [my_c] if my_c in _cfg_committees() else []
    if not scope:
        abort(403)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "Committee", "Delegation", "POI count", "Speech count",
        "Amendment count", "Total points",
    ])

    for c in scope:
        delegations = set()
        for r in db.execute(
            """SELECT DISTINCT delegation FROM users
               WHERE committee = ? AND delegation IS NOT NULL AND delegation != ''""",
            (c,),
        ).fetchall():
            delegations.add(r["delegation"])
        for r in db.execute(
            "SELECT DISTINCT delegation FROM tally_entries WHERE committee = ?",
            (c,),
        ).fetchall():
            delegations.add(r["delegation"])

        rows = db.execute(
            """SELECT delegation, kind, COUNT(*) AS n, SUM(points) AS pts
               FROM tally_entries
               WHERE committee = ? AND reset_id IS NULL
               GROUP BY delegation, kind""",
            (c,),
        ).fetchall()
        tallies = {
            d: {"poi": 0, "speech": 0, "amendment": 0, "total": 0}
            for d in delegations
        }
        for r in rows:
            d = r["delegation"]
            tallies.setdefault(d, {"poi": 0, "speech": 0, "amendment": 0, "total": 0})
            tallies[d][r["kind"]] = r["n"]
            tallies[d]["total"] += r["pts"]
        ordered = sorted(tallies.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
        for d, t in ordered:
            writer.writerow([c, d, t["poi"], t["speech"], t["amendment"], t["total"]])

    csv_data = out.getvalue()
    date_str = datetime.now().strftime("%Y-%m-%d")
    scope_part = "all" if g.user["role"] == "admin" else scope[0].lower()
    filename = f"mundp-tally-{scope_part}-{date_str}.csv"
    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/tally/<int:entry_id>/delete", methods=["POST"])
@roles_required("chair")
def delete_tally(entry_id: int):
    db = get_db()
    row = db.execute(
        "SELECT committee, delegation FROM tally_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    if not row:
        if _wants_json():
            return jsonify({"ok": False, "error": "Not found."}), 404
        abort(404)
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        if _wants_json():
            return jsonify({"ok": False, "error": "Forbidden."}), 403
        abort(403)
    db.execute("DELETE FROM tally_entries WHERE id = ?", (entry_id,))
    db.commit()

    if _wants_json():
        totals = _delegation_totals(db, row["committee"], row["delegation"])
        return jsonify({
            "ok": True,
            "committee": row["committee"],
            "delegation": row["delegation"],
            "totals": totals,
        })

    flash("Entry undone.", "success")
    return redirect(url_for("tally"))


# ---------------------------------------------------------------------------
# Schedule (placeholder page) and Contact form
# ---------------------------------------------------------------------------
@app.route("/my-committee")
@login_required
def my_committee():
    # exec_gc can browse any committee via ?c= query param
    if g.user["role"] == "exec_gc":
        from flask import request as _req
        committee = (_req.args.get("c") or "").strip()
        if not committee or committee not in _cfg_committees():
            return render_template(
                "my_committee.html",
                committee=None,
                all_committees=_cfg_committees(),
            )
    else:
        committee = (g.user.get("committee") or "").strip()
        if not committee or committee not in _cfg_committees():
            return render_template("my_committee.html", committee=None)

    db = get_db()
    vis_sql, vis_params = _doc_visibility_clause("d")
    rows = db.execute(
        f"""
        SELECT d.id, d.title, d.created_at, d.status, d.size_bytes, d.approved,
               d.in_debate, d.uploader_id,
               u.display_name AS uploader_name,
               (SELECT COUNT(*) FROM comments c WHERE c.document_id = d.id) AS comment_count
        FROM documents d
        JOIN users u ON u.id = d.uploader_id
        WHERE d.committee = ? AND {vis_sql}
        ORDER BY d.created_at DESC
        """,
        [committee, *vis_params],
    ).fetchall()
    # Resolutions that haven't been approved yet sit in their own bucket.
    awaiting = [r for r in rows if not r["approved"]]
    approved = [r for r in rows if r["approved"]]
    debated = [r for r in approved if r["status"] in ("debated", "passed", "failed")]
    pending = [r for r in approved if r["status"] not in ("debated", "passed", "failed")]

    committee_members = db.execute(
        """
        SELECT id, display_name, delegation, role, outside_since,
               upload_permission_until
        FROM users
        WHERE committee = ? AND id != ? AND role = 'delegate'
        ORDER BY display_name
        """,
        (committee, g.user["id"]),
    ).fetchall()

    notes_in_committee = []
    if g.user["role"] in ("chair", "admin"):
        notes_in_committee = db.execute(
            """
            SELECT n.id, n.body, n.created_at, n.sender_delegation,
                   n.recipient_delegation, u.display_name AS sender_name
            FROM notes n
            JOIN users u ON u.id = n.sender_id
            WHERE n.committee = ?
            ORDER BY n.created_at DESC
            """,
            (committee,),
        ).fetchall()

    # Tally summary for admin and exec_gc
    committee_tally = []
    if g.user["role"] in ("admin", "exec_gc"):
        tally_delegations = set()
        for r in db.execute(
            "SELECT DISTINCT delegation FROM users WHERE committee = ? AND role = 'delegate'",
            (committee,),
        ).fetchall():
            if r["delegation"]:
                tally_delegations.add(r["delegation"])
        for r in db.execute(
            "SELECT DISTINCT delegation FROM tally_entries WHERE committee = ?",
            (committee,),
        ).fetchall():
            if r["delegation"]:
                tally_delegations.add(r["delegation"])
        tally_rows = db.execute(
            """SELECT delegation, kind, COUNT(*) AS n, SUM(points) AS pts
               FROM tally_entries
               WHERE committee = ? AND reset_id IS NULL
               GROUP BY delegation, kind""",
            (committee,),
        ).fetchall()
        tallies = {d: {"poi": 0, "speech": 0, "amendment": 0, "total": 0} for d in tally_delegations}
        for r in tally_rows:
            d = r["delegation"]
            if d not in tallies:
                tallies[d] = {"poi": 0, "speech": 0, "amendment": 0, "total": 0}
            tallies[d][r["kind"]] = r["n"]
            tallies[d]["total"] += r["pts"]
        committee_tally = sorted(tallies.items(), key=lambda kv: (-kv[1]["total"], kv[0]))

    return render_template(
        "my_committee.html",
        committee=committee,
        info=_cfg_committee_info()[committee],
        debated=debated,
        pending=pending,
        awaiting=awaiting,
        committee_members=committee_members,
        notes_in_committee=notes_in_committee,
        committee_tally=committee_tally,
        now_utc_iso=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/committee/permit-upload/<int:user_id>", methods=["POST"])
@login_required
def grant_upload_permission(user_id: int):
    """Chair (or admin) grants a delegate a 10-minute upload window."""
    if g.user["role"] not in ("chair", "admin"):
        abort(403)
    db = get_db()
    target = db.execute(
        "SELECT id, role, committee, display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not target or target["role"] != "delegate":
        flash("Only delegates can be granted upload permission.", "error")
        return redirect(url_for("my_committee"))
    if g.user["role"] == "chair":
        if (target["committee"] or "") != (g.user.get("committee") or ""):
            flash("You can only grant permission to delegates in your own committee.", "error")
            return redirect(url_for("my_committee"))
    until = datetime.now(timezone.utc) + timedelta(minutes=_cfg_upload_minutes())
    db.execute(
        "UPDATE users SET upload_permission_until = ? WHERE id = ?",
        (until.isoformat(), user_id),
    )
    db.commit()
    flash(
        f"Granted {target['display_name']} {_cfg_upload_minutes()} minutes "
        "to upload a resolution.",
        "success",
    )
    return redirect(request.referrer or url_for("my_committee"))


@app.route("/committee/revoke-upload/<int:user_id>", methods=["POST"])
@login_required
def revoke_upload_permission(user_id: int):
    if g.user["role"] not in ("chair", "admin"):
        abort(403)
    db = get_db()
    target = db.execute(
        "SELECT id, role, committee, display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not target:
        abort(404)
    if g.user["role"] == "chair":
        if (target["committee"] or "") != (g.user.get("committee") or ""):
            flash("You can only revoke delegates in your own committee.", "error")
            return redirect(url_for("my_committee"))
    db.execute(
        "UPDATE users SET upload_permission_until = NULL WHERE id = ?", (user_id,)
    )
    db.commit()
    flash(f"Revoked {target['display_name']}'s upload permission.", "success")
    return redirect(request.referrer or url_for("my_committee"))


@app.route("/documents/<int:doc_id>/status", methods=["POST"])
@roles_required("chair")
def set_document_status(doc_id: int):
    new_status = (request.form.get("status") or "").strip()
    if new_status not in VALID_DOC_STATUSES:
        abort(400, description="Invalid status.")
    db = get_db()
    row = db.execute(
        "SELECT id, committee FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row:
        abort(404)
    # Chairs may only act on their own committee. Admins always pass.
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        abort(403, description="You can only update resolutions in your own committee.")
    db.execute("UPDATE documents SET status = ? WHERE id = ?", (new_status, doc_id))
    db.commit()
    flash(f"Marked as {new_status}.", "success")
    return redirect(request.form.get("next") or url_for("view_document", doc_id=doc_id))


@app.route("/documents/<int:doc_id>/in_debate", methods=["POST"])
@roles_required("chair")
def toggle_in_debate(doc_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, committee, in_debate FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row:
        abort(404)
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        abort(403, description="You can only update resolutions in your own committee.")
    new_val = 0 if row["in_debate"] else 1
    db.execute("UPDATE documents SET in_debate = ? WHERE id = ?", (new_val, doc_id))
    db.commit()
    flash(
        "Resolution is now visible to the house." if new_val
        else "Resolution is no longer visible to the house.",
        "success",
    )
    return redirect(url_for("view_document", doc_id=doc_id))


def _vote_tally(db, doc_id: int) -> dict:
    """Return current vote breakdown for a document."""
    out = {"for": 0, "against": 0}
    for r in db.execute(
        "SELECT choice, COUNT(*) AS n FROM votes WHERE document_id = ? GROUP BY choice",
        (doc_id,),
    ).fetchall():
        out[r["choice"]] = r["n"]
    return out


def _chair_owns_doc(doc) -> bool:
    user = g.user
    if user["role"] == "admin":
        return True
    if user["role"] == "chair" and doc["committee"] == user.get("committee"):
        return True
    return False


@app.route("/documents/<int:doc_id>/voting/<action>", methods=["POST"])
@roles_required("chair")
def voting_control(doc_id: int, action: str):
    if action not in ("open", "lock", "reset"):
        abort(404)
    db = get_db()
    row = db.execute(
        "SELECT id, committee, approved, voting_status, title FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if not _chair_owns_doc(row):
        abort(403)
    if not row["approved"]:
        flash("Approve the resolution before opening a vote.", "error")
        return redirect(url_for("view_document", doc_id=doc_id))

    if action == "open":
        db.execute(
            "UPDATE documents SET voting_status='open', voting_locked_at=NULL WHERE id=?",
            (doc_id,),
        )
        db.commit()
        flash("Voting opened. Delegates can now cast their vote.", "success")
    elif action == "reset":
        db.execute("DELETE FROM votes WHERE document_id=?", (doc_id,))
        db.execute(
            "UPDATE documents SET voting_status='closed', voting_locked_at=NULL WHERE id=?",
            (doc_id,),
        )
        db.commit()
        flash("Voting reset — all votes cleared.", "success")
    elif action == "lock":
        tally = _vote_tally(db, doc_id)
        new_status = row["voting_status"]
        # Lock the vote and auto-set the resolution's status.
        if tally["for"] > tally["against"]:
            doc_status = "passed"
        elif tally["against"] > tally["for"]:
            doc_status = "failed"
        else:
            doc_status = "debated"  # tie: chair can override afterward
        db.execute(
            """UPDATE documents
               SET voting_status='locked',
                   voting_locked_at=datetime('now'),
                   status=?
               WHERE id=?""",
            (doc_status, doc_id),
        )
        db.commit()
        flash(
            f"Vote locked. Tally — For: {tally['for']}, Against: {tally['against']}. "
            f"Resolution marked as {doc_status}.",
            "success",
        )
    return redirect(url_for("view_document", doc_id=doc_id))


@app.route("/documents/<int:doc_id>/vote", methods=["POST"])
@login_required
def cast_vote(doc_id: int):
    choice = (request.form.get("choice") or "").strip()
    if choice not in ("for", "against"):
        abort(400, description="Invalid choice.")
    db = get_db()
    row = db.execute(
        "SELECT id, committee, voting_status, approved FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if not row["approved"] or row["voting_status"] != "open":
        flash("Voting is not open on this resolution.", "error")
        return redirect(url_for("view_document", doc_id=doc_id))
    # Only delegates whose committee matches may vote.
    if g.user["role"] != "delegate" or g.user.get("committee") != row["committee"]:
        abort(403, description="Only delegates of this committee can vote.")
    db.execute(
        """INSERT INTO votes (document_id, voter_id, choice)
           VALUES (?, ?, ?)
           ON CONFLICT(document_id, voter_id) DO UPDATE SET
               choice = excluded.choice,
               updated_at = datetime('now')""",
        (doc_id, g.user["id"], choice),
    )
    db.commit()
    flash(f"Vote recorded ({choice}). You can change it until voting is locked.", "success")
    return redirect(url_for("view_document", doc_id=doc_id))


@app.route("/documents/<int:doc_id>/body", methods=["GET"])
@login_required
def get_document_body(doc_id: int):
    """Lightweight JSON endpoint used by viewers to poll the working text."""
    db = get_db()
    row = db.execute(
        """SELECT id, committee, approved, uploader_id,
                  body_text, body_updated_at
           FROM documents WHERE id = ?""",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if not row["approved"]:
        if g.user["role"] not in ("admin", "chair") and row["uploader_id"] != g.user["id"]:
            abort(404)
        if g.user["role"] == "chair" and row["committee"] != g.user.get("committee"):
            abort(404)
    return jsonify({
        "ok": True,
        "body_text": row["body_text"] or "",
        "body_updated_at": row["body_updated_at"] or "",
    })


@app.route("/documents/<int:doc_id>/text", methods=["POST"])
@roles_required("chair")
def update_document_text(doc_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, committee FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not row:
        if _wants_json():
            return jsonify({"ok": False, "error": "Not found."}), 404
        abort(404)
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        if _wants_json():
            return jsonify({"ok": False, "error": "Forbidden."}), 403
        abort(403)
    new_body = request.form.get("body_text") or ""
    if len(new_body) > 50000:
        if _wants_json():
            return jsonify({"ok": False, "error": "Working text too long (max 50 000 characters)."}), 400
        flash("Working text too long (max 50 000 characters).", "error")
        return redirect(url_for("view_document", doc_id=doc_id))
    db.execute(
        """UPDATE documents
           SET body_text = ?,
               body_updated_at = datetime('now'),
               body_updated_by = ?
           WHERE id = ?""",
        (new_body or None, g.user["id"], doc_id),
    )
    db.commit()
    if _wants_json():
        updated_at = db.execute(
            "SELECT body_updated_at FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()["body_updated_at"]
        return jsonify({"ok": True, "body_updated_at": updated_at or ""})
    flash("Working text saved.", "success")
    return redirect(url_for("view_document", doc_id=doc_id))


@app.route("/documents/<int:doc_id>/approve", methods=["POST"])
@roles_required("chair")
def approve_document(doc_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, committee, approved, title, uploader_id FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        abort(403, description="You can only approve resolutions in your own committee.")
    if row["approved"]:
        flash("Already approved.", "error")
        return redirect(url_for("view_document", doc_id=doc_id))
    db.execute(
        """UPDATE documents
           SET approved = 1, approved_at = datetime('now'), approved_by = ?
           WHERE id = ?""",
        (g.user["id"], doc_id),
    )
    db.commit()
    flash(f"Approved '{row['title']}'. The uploader and committee can now see it.", "success")
    return redirect(url_for("view_document", doc_id=doc_id))


@app.route("/documents/<int:doc_id>/summit", methods=["POST"])
@roles_required("chair")
def toggle_summit(doc_id: int):
    db = get_db()
    row = db.execute(
        "SELECT id, committee, is_summit, title FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if not row["committee"]:
        abort(400, description="Resolution has no committee.")
    if g.user["role"] != "admin" and row["committee"] != g.user.get("committee"):
        abort(403, description="You can only submit resolutions from your own committee.")

    if row["is_summit"]:
        db.execute("UPDATE documents SET is_summit = 0 WHERE id = ?", (doc_id,))
        db.commit()
        flash(f"'{row['title']}' withdrawn from the International Summit.", "success")
    else:
        # Demote any current summit submission for this committee, then promote.
        prev = db.execute(
            "SELECT id, title FROM documents WHERE committee = ? AND is_summit = 1",
            (row["committee"],),
        ).fetchone()
        if prev and prev["id"] != doc_id:
            db.execute("UPDATE documents SET is_summit = 0 WHERE id = ?", (prev["id"],))
        db.execute("UPDATE documents SET is_summit = 1 WHERE id = ?", (doc_id,))
        db.commit()
        if prev and prev["id"] != doc_id:
            flash(
                f"'{row['title']}' is now the summit submission. '{prev['title']}' was withdrawn.",
                "success",
            )
        else:
            flash(f"'{row['title']}' submitted to the International Summit.", "success")
    return redirect(request.form.get("next") or url_for("view_document", doc_id=doc_id))


@app.route("/api/badges")
@login_required
def api_badges():
    """Lightweight JSON snapshot for live sidebar updates."""
    return jsonify({"ok": True, "badges": _compute_badges()})


@app.route("/api/documents/<int:doc_id>/voting")
@login_required
def api_voting(doc_id: int):
    """Live voting state for a resolution: status, tally, my vote, doc.status."""
    db = get_db()
    row = db.execute(
        """SELECT id, committee, approved, uploader_id, voting_status, status
           FROM documents WHERE id = ?""",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if not row["approved"]:
        if g.user["role"] not in ("admin", "chair") and row["uploader_id"] != g.user["id"]:
            abort(404)
        if g.user["role"] == "chair" and row["committee"] != g.user.get("committee"):
            abort(404)
    tally = _vote_tally(db, doc_id)
    eligible = db.execute(
        "SELECT COUNT(*) FROM users WHERE role='delegate' AND committee=?",
        (row["committee"],),
    ).fetchone()[0] if row["committee"] else 0
    my_vote_row = db.execute(
        "SELECT choice FROM votes WHERE document_id=? AND voter_id=?",
        (doc_id, g.user["id"]),
    ).fetchone()
    return jsonify({
        "ok": True,
        "voting_status": row["voting_status"],
        "doc_status": row["status"],
        "approved": bool(row["approved"]),
        "tally": tally,
        "eligible_voters": eligible,
        "my_vote": my_vote_row["choice"] if my_vote_row else None,
    })


@app.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    user = g.user
    committee = (user.get("committee") or "").strip() or None
    db = get_db()

    if request.method == "POST":
        # Advisors send notes only to the Chairboard of a committee they advise.
        if user["role"] == "advisor":
            target_committee = (request.form.get("committee") or "").strip()
            if target_committee not in _cfg_committees():
                flash("Pick a committee for your note.", "error")
                return redirect(url_for("notes"))
            # Restrict to committees this advisor is actually assigned to.
            allowed = {r["committee"] for r in db.execute(
                "SELECT DISTINCT committee FROM advisor_assignments WHERE advisor_id = ?",
                (user["id"],),
            ).fetchall()}
            if target_committee not in allowed:
                flash("You can only message Chairboards of committees you advise.", "error")
                return redirect(url_for("notes"))
            recipient_forced = "Chairboard"
            request.form = request.form.copy()  # immutable MultiDict; we'll
            # just use recipient_forced directly below.
            sender_label = user.get("participant_name") or user["display_name"]
            sender_delegation = f"Advisor: {sender_label}"
            body = (request.form.get("body") or "").strip()
            if not body:
                flash("Note body cannot be empty.", "error")
                return redirect(url_for("notes"))
            if len(body) > 2000:
                flash("Note too long (max 2000 characters).", "error")
                return redirect(url_for("notes"))
            db.execute(
                """INSERT INTO notes (sender_id, sender_delegation, committee,
                                      recipient_delegation, body)
                   VALUES (?, ?, ?, ?, ?)""",
                (user["id"], sender_delegation, target_committee,
                 recipient_forced, body),
            )
            db.commit()
            flash(f"Note sent to {target_committee} Chairboard.", "success")
            return redirect(url_for("notes"))

        # Admins can send into any committee; they pick one per note.
        if user["role"] == "admin":
            target_committee = (request.form.get("committee") or "").strip()
            if target_committee not in _cfg_committees():
                flash("Pick a committee for your note.", "error")
                return redirect(url_for("notes"))
            sender_delegation = (user.get("delegation") or "").strip() or "Admin"
        elif user["role"] == "chair":
            # Chairs run their committee — they can message any delegation
            # in that committee without an assigned delegation of their own.
            if not committee:
                flash("You must be assigned to a committee to send notes.", "error")
                return redirect(url_for("notes"))
            target_committee = committee
            sender_delegation = (user.get("delegation") or "").strip() or "Chair"
        else:
            if not committee:
                flash("You must be assigned to a committee to send notes.", "error")
                return redirect(url_for("notes"))
            if not (user.get("delegation") or "").strip():
                flash("Your delegation isn't set. Ask an admin to assign one.", "error")
                return redirect(url_for("notes"))
            target_committee = committee
            sender_delegation = user["delegation"]

        recipient = (request.form.get("recipient_delegation") or "").strip()
        body = (request.form.get("body") or "").strip()

        if not recipient:
            flash("Please choose a recipient.", "error")
            return redirect(url_for("notes"))
        if recipient == sender_delegation and sender_delegation != "Admin":
            flash("You can't pass a note to your own delegation.", "error")
            return redirect(url_for("notes"))
        if not body:
            flash("Note body cannot be empty.", "error")
            return redirect(url_for("notes"))
        if len(body) > 2000:
            flash("Note too long (max 2000 characters).", "error")
            return redirect(url_for("notes"))

        db.execute(
            """
            INSERT INTO notes (sender_id, sender_delegation, committee,
                               recipient_delegation, body)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user["id"], sender_delegation, target_committee, recipient, body),
        )
        db.commit()
        flash("Note sent.", "success")
        return redirect(url_for("notes"))

    # GET — fetch notes visible to this user
    if user["role"] == "advisor":
        rows = db.execute(
            """
            SELECT n.id, n.body, n.created_at, n.committee,
                   n.sender_delegation, n.recipient_delegation,
                   u.display_name AS sender_name
            FROM notes n
            JOIN users u ON u.id = n.sender_id
            WHERE n.sender_id = ?
            ORDER BY n.created_at DESC
            """,
            (user["id"],),
        ).fetchall()
        # Committees this advisor can post to (used by the compose form).
        advised_committees = sorted({r["committee"] for r in db.execute(
            "SELECT DISTINCT committee FROM advisor_assignments WHERE advisor_id = ?",
            (user["id"],),
        ).fetchall()})
        inbox_label = "Notes you've sent"
        _mark_seen("notes_last_seen_at")
        return render_template(
            "notes.html",
            notes=rows,
            inbox_label=inbox_label,
            user_committee=None,
            committees=advised_committees,
        )

    if user["role"] == "admin":
        rows = db.execute(
            """
            SELECT n.id, n.body, n.created_at, n.committee,
                   n.sender_delegation, n.recipient_delegation,
                   u.display_name AS sender_name
            FROM notes n
            JOIN users u ON u.id = n.sender_id
            ORDER BY n.created_at DESC
            """
        ).fetchall()
        inbox_label = "All notes (admin view)"
    elif user["role"] == "chair" and committee:
        rows = db.execute(
            """
            SELECT n.id, n.body, n.created_at, n.committee,
                   n.sender_delegation, n.recipient_delegation,
                   u.display_name AS sender_name
            FROM notes n
            JOIN users u ON u.id = n.sender_id
            WHERE n.committee = ?
            ORDER BY n.created_at DESC
            """,
            (committee,),
        ).fetchall()
        inbox_label = f"All notes in {committee}"
    elif committee and user.get("delegation"):
        rows = db.execute(
            """
            SELECT n.id, n.body, n.created_at, n.committee,
                   n.sender_delegation, n.recipient_delegation,
                   u.display_name AS sender_name
            FROM notes n
            JOIN users u ON u.id = n.sender_id
            WHERE n.committee = ?
              AND (n.sender_id = ? OR n.recipient_delegation = ?)
            ORDER BY n.created_at DESC
            """,
            (committee, user["id"], user["delegation"]),
        ).fetchall()
        inbox_label = "Your notes"
    else:
        rows = []
        inbox_label = "Your notes"

    _mark_seen("notes_last_seen_at")
    return render_template(
        "notes.html",
        notes=rows,
        inbox_label=inbox_label,
        user_committee=committee,
        committees=_cfg_committees(),
    )


@app.route("/settings")
@login_required
def settings():
    db = get_db()
    me = db.execute(
        """SELECT id, username, display_name, participant_name, email, phone,
                  role, committee, delegation, created_at
           FROM users WHERE id = ?""",
        (g.user["id"],),
    ).fetchone()
    other_sessions = db.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ?",
        (g.user["id"],),
    ).fetchone()[0]
    # one of those is the current request's session — subtract it
    if other_sessions > 0:
        other_sessions -= 1
    return render_template("settings.html", me=me, other_sessions=other_sessions)


@app.route("/settings/contact", methods=["POST"])
@login_required
def settings_update_contact():
    email = (request.form.get("email") or "").strip() or None
    phone = (request.form.get("phone") or "").strip() or None
    if email and len(email) > 200:
        flash("Email too long.", "error")
        return redirect(url_for("settings"))
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        flash("That doesn't look like a valid email address.", "error")
        return redirect(url_for("settings"))
    if phone and len(phone) > 40:
        flash("Phone too long.", "error")
        return redirect(url_for("settings"))
    db = get_db()
    db.execute(
        "UPDATE users SET email = ?, phone = ? WHERE id = ?",
        (email, phone, g.user["id"]),
    )
    db.commit()
    flash("Contact details updated.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/password", methods=["POST"])
@login_required
def settings_change_password():
    current = request.form.get("current_password") or ""
    new1 = request.form.get("new_password") or ""
    new2 = request.form.get("new_password_confirm") or ""
    db = get_db()
    row = db.execute(
        "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)
    ).fetchone()
    if not row or not verify_password(current, row["password_hash"]):
        flash("Current password is incorrect.", "error")
        return redirect(url_for("settings"))
    if len(new1) < 8:
        flash("New password must be at least 8 characters.", "error")
        return redirect(url_for("settings"))
    if new1 != new2:
        flash("New passwords don't match.", "error")
        return redirect(url_for("settings"))
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new1), g.user["id"]),
    )
    # Sign out any other active sessions for this user.
    current_token = request.cookies.get(SESSION_COOKIE)
    db.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token != ?",
        (g.user["id"], current_token or ""),
    )
    db.commit()
    flash("Password updated. Other devices signed out.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/sign-out-others", methods=["POST"])
@login_required
def settings_sign_out_others():
    db = get_db()
    current_token = request.cookies.get(SESSION_COOKIE)
    cur = db.execute(
        "DELETE FROM sessions WHERE user_id = ? AND token != ?",
        (g.user["id"], current_token or ""),
    )
    db.commit()
    if cur.rowcount:
        flash(f"Signed out {cur.rowcount} other session{'s' if cur.rowcount != 1 else ''}.", "success")
    else:
        flash("No other sessions were active.", "success")
    return redirect(url_for("settings"))


@app.route("/credits")
@login_required
def credits():
    return render_template("credits.html")


@app.route("/help")
@login_required
def help_page():
    return render_template("help.html")


@app.route("/schedule")
@login_required
def schedule():
    return render_template("schedule.html", schedule=_cfg_schedule(), location=_cfg_conference().get("location", ""))




@app.route("/contact", methods=["GET", "POST"])
@login_required
def contact():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        subject = (request.form.get("subject") or "").strip()
        body = (request.form.get("body") or "").strip()

        if not name or not body:
            flash("Name and message are required.", "error")
            return render_template(
                "contact.html",
                secretariat_email=_cfg_conference().get("secretariat_email", ""),
                form={"name": name, "email": email, "subject": subject, "body": body},
            )
        if len(body) > 5000:
            flash("Message too long (max 5000 characters).", "error")
            return render_template(
                "contact.html",
                secretariat_email=_cfg_conference().get("secretariat_email", ""),
                form={"name": name, "email": email, "subject": subject, "body": body},
            )

        db = get_db()
        db.execute(
            """
            INSERT INTO messages (name, email, subject, body, sender_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, email or None, subject or None, body, g.user["id"]),
        )
        db.commit()
        _sec = _cfg_conference().get("secretariat_email", "")
        flash(f"Your message has been sent to {_sec}.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html", secretariat_email=_cfg_conference().get("secretariat_email", ""), form={})


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    # Advisors are read-only; they don't upload.
    if g.user["role"] == "advisor":
        abort(403)
    # Admins can upload to any committee; chairs and delegates are locked to
    # their own committee and must pick from that committee's agenda items.
    if g.user["role"] == "admin":
        allowed_committees = list(_cfg_committees())
        locked_committee = None
    else:
        user_committee = (g.user.get("committee") or "").strip()
        if not user_committee or user_committee not in _cfg_committees():
            flash("You haven't been assigned to a committee yet.", "error")
            return redirect(url_for("dashboard"))
        allowed_committees = [user_committee]
        locked_committee = user_committee

    # Delegates need an active 10-minute permission window granted by a chair.
    permission_blocked = False
    permission_until = None
    if g.user["role"] == "delegate":
        permission_until = _upload_permission_until(g.user["id"])
        permission_blocked = permission_until is None

    def render_form():
        return render_template(
            "upload.html",
            committees=allowed_committees,
            locked_committee=locked_committee,
            committee_info=_cfg_committee_info(),
            permission_blocked=permission_blocked,
            permission_until_iso=(permission_until.isoformat() if permission_until else None),
        )

    if request.method == "POST":
        if permission_blocked:
            flash("Your upload permission has not been granted or has expired.", "error")
            return render_form()
        committee = (request.form.get("committee") or "").strip()
        if locked_committee:
            committee = locked_committee
        agenda_item = (request.form.get("agenda_item") or "").strip()
        google_doc_url_raw = (request.form.get("google_doc_url") or "").strip()
        if not google_doc_url_raw:
            flash("Google Doc URL is required.", "error")
            return render_form()
        google_doc_url = _normalize_google_doc_url(google_doc_url_raw)
        if not google_doc_url:
            flash(
                "Google Doc URL must look like https://docs.google.com/document/d/...",
                "error",
            )
            return render_form()
        file = request.files.get("file")
        description = None

        if committee not in allowed_committees:
            flash("You can only upload to your own committee.", "error")
            return render_form()
        valid_agenda = [a for a in _cfg_committee_info()[committee]["agenda_items"] if a]
        if not agenda_item or agenda_item not in valid_agenda:
            flash("Pick an agenda item for this resolution.", "error")
            return render_form()

        # Auto-generate the title: "COMMITTEE AGENDA# - SUBMISSION#"
        # Agenda# is 1-indexed position in the committee's agenda_items.
        # Submission# is one more than the highest "- N" number found in
        # existing titles for this (committee, agenda_item) — robust to deletes.
        db_t = get_db()
        agenda_index = valid_agenda.index(agenda_item) + 1
        existing_titles = db_t.execute(
            "SELECT title FROM documents WHERE committee = ? AND agenda_item = ?",
            (committee, agenda_item),
        ).fetchall()
        title_re = _re.compile(rf"^{_re.escape(committee)}\s+{agenda_index}\s*-\s*(\d+)$")
        max_num = 0
        for row in existing_titles:
            m = title_re.match((row["title"] or "").strip())
            if m:
                max_num = max(max_num, int(m.group(1)))
        submission_number = max_num + 1
        title = f"{committee} {agenda_index} - {submission_number}"

        # PDF is now optional. If provided, validate as before.
        original_name = None
        stored_name = None
        size = 0
        if file and file.filename:
            if not file.filename.lower().endswith(".pdf"):
                flash("Only PDF files are allowed.", "error")
                return render_form()
            original_name = secure_filename(file.filename)
            stored_name = f"{uuid.uuid4().hex}.pdf"
            dest = os.path.join(UPLOAD_DIR, stored_name)
            file.save(dest)
            with open(dest, "rb") as fh:
                head = fh.read(5)
            if head != b"%PDF-":
                os.remove(dest)
                flash("File does not look like a valid PDF.", "error")
                return render_form()
            size = os.path.getsize(dest)
        db = get_db()
        # Delegates' resolutions are queued for chair approval; chair/admin
        # uploads are auto-approved by themselves.
        is_delegate = g.user["role"] == "delegate"
        approved = 0 if is_delegate else 1
        approved_by = None if is_delegate else g.user["id"]
        cur = db.execute(
            """
            INSERT INTO documents
                (title, description, filename, stored_name, size_bytes,
                 committee, agenda_item, google_doc_url,
                 approved, approved_by, approved_at, uploader_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ? = 1 THEN datetime('now') ELSE NULL END,
                    ?)
            """,
            (title, description, original_name, stored_name, size,
             committee, agenda_item, google_doc_url,
             approved, approved_by,
             approved, g.user["id"]),
        )
        db.commit()
        if is_delegate:
            flash("Resolution submitted — awaiting chair approval.", "success")
        else:
            flash("Resolution uploaded.", "success")
        return redirect(url_for("view_document", doc_id=cur.lastrowid))

    return render_form()


# ---------------------------------------------------------------------------
# View document + comments
# ---------------------------------------------------------------------------
@app.route("/documents/<int:doc_id>")
@login_required
def view_document(doc_id: int):
    db = get_db()
    doc = db.execute(
        """
        SELECT d.id, d.title, d.description, d.filename, d.stored_name,
               d.size_bytes, d.committee, d.agenda_item, d.status, d.is_summit,
               d.approved, d.approved_at, d.voting_status, d.voting_locked_at,
               d.in_debate,
               d.body_text, d.body_updated_at, d.body_updated_by,
               d.google_doc_url,
               d.created_at, d.uploader_id,
               u.display_name AS uploader_name,
               u.delegation   AS uploader_delegation,
               u.role         AS uploader_role
        FROM documents d
        JOIN users u ON u.id = d.uploader_id
        WHERE d.id = ?
        """,
        (doc_id,),
    ).fetchone()
    if doc and not doc["approved"]:
        if g.user["role"] not in ("admin", "chair") and doc["uploader_id"] != g.user["id"]:
            abort(404)
        if (g.user["role"] == "chair"
                and doc["committee"] != g.user.get("committee")):
            abort(404)
    if doc and doc["approved"] and g.user["role"] == "delegate":
        # Delegates may only read a resolution that is in debate, already
        # debated/voted on, or that they uploaded themselves.
        readable = (
            doc["uploader_id"] == g.user["id"]
            or doc["in_debate"]
            or doc["status"] in ("debated", "passed", "failed")
        )
        if not readable:
            abort(403)

    vote_tally = {"for": 0, "against": 0}
    eligible_voters = 0
    my_vote = None
    if doc:
        vote_tally = _vote_tally(db, doc_id)
        eligible_voters = db.execute(
            "SELECT COUNT(*) FROM users WHERE role='delegate' AND committee=?",
            (doc["committee"],),
        ).fetchone()[0] if doc["committee"] else 0
        row = db.execute(
            "SELECT choice FROM votes WHERE document_id=? AND voter_id=?",
            (doc_id, g.user["id"]),
        ).fetchone()
        my_vote = row["choice"] if row else None
    if not doc:
        abort(404)
    google_doc_id = _google_doc_id(doc["google_doc_url"]) if doc else None
    google_doc_embed_url = (
        f"https://docs.google.com/document/d/{google_doc_id}/preview"
        if google_doc_id else None
    )
    return render_template(
        "document.html",
        doc=doc,
        vote_tally=vote_tally,
        eligible_voters=eligible_voters,
        my_vote=my_vote,
        google_doc_embed_url=google_doc_embed_url,
    )


@app.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id: int):
    db = get_db()
    row = db.execute(
        "SELECT stored_name, uploader_id FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if g.user["role"] != "admin" and row["uploader_id"] != g.user["id"]:
        abort(403)
    # Remove DB row first (cascades to comments); then the file. If the file
    # delete fails (e.g. already gone), we don't roll back the DB.
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    db.commit()
    try:
        os.remove(os.path.join(UPLOAD_DIR, row["stored_name"]))
    except FileNotFoundError:
        pass
    flash("Document deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/documents/<int:doc_id>/file")
@login_required
def serve_document(doc_id: int):
    db = get_db()
    row = db.execute(
        "SELECT stored_name, filename, approved, in_debate, status, uploader_id FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not row:
        abort(404)
    if row["approved"] and g.user["role"] == "delegate":
        readable = (
            row["uploader_id"] == g.user["id"]
            or row["in_debate"]
            or row["status"] in ("debated", "passed", "failed")
        )
        if not readable:
            abort(403)
    return send_from_directory(
        UPLOAD_DIR, row["stored_name"],
        mimetype="application/pdf",
        download_name=row["filename"],
        as_attachment=False,
    )


@app.route("/documents/<int:doc_id>/comments", methods=["GET", "POST"])
@login_required
def comments(doc_id: int):
    db = get_db()
    doc = db.execute(
        "SELECT id, approved, uploader_id, committee, in_debate, status FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    if not doc:
        abort(404)
    if not doc["approved"]:
        if g.user["role"] not in ("admin", "chair") and doc["uploader_id"] != g.user["id"]:
            abort(404)
        if g.user["role"] == "chair" and doc["committee"] != g.user.get("committee"):
            abort(404)
    if doc["approved"] and g.user["role"] == "delegate":
        readable = (
            doc["uploader_id"] == g.user["id"]
            or doc["in_debate"]
            or doc["status"] in ("debated", "passed", "failed")
        )
        if not readable:
            abort(403)

    if request.method == "POST":
        if g.user["role"] != "delegate":
            return jsonify({
                "error": "Only delegates may submit amendments. Chairs review them."
            }), 403
        if (g.user.get("committee") or "").strip() != (doc["committee"] or "").strip():
            return jsonify({
                "error": "You can only amend resolutions in your own committee."
            }), 403
        # Finalized resolutions are not amendable.
        status_row = db.execute(
            "SELECT status FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if status_row and status_row["status"] in ("passed", "failed"):
            return jsonify({
                "error": "This resolution is finalized — amendments are closed."
            }), 403
        data = request.get_json(silent=True) or {}
        body = (data.get("body") or "").strip()
        page = data.get("page_number")
        clause = (data.get("clause") or "").strip()
        sub_clause = (data.get("sub_clause") or "").strip()
        sub_sub_clause = (data.get("sub_sub_clause") or "").strip()
        if not body:
            return jsonify({"error": "Amendment body is required."}), 400
        if len(body) > 5000:
            return jsonify({"error": "Amendment too long (max 5000 chars)."}), 400
        if not clause:
            return jsonify({
                "error": "Specify the clause this amendment targets."
            }), 400
        try:
            page_val = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_val = None
        cur = db.execute(
            """
            INSERT INTO comments
                (document_id, author_id, page_number,
                 clause, sub_clause, sub_sub_clause, body)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, g.user["id"], page_val,
             clause, sub_clause or None, sub_sub_clause or None, body),
        )
        db.commit()
        new_id = cur.lastrowid
        row = db.execute(
            """
            SELECT c.id, c.body, c.page_number, c.created_at,
                   c.clause, c.sub_clause, c.sub_sub_clause,
                   u.display_name AS author_name, u.role AS author_role,
                   u.delegation   AS author_delegation
            FROM comments c
            JOIN users u ON u.id = c.author_id
            WHERE c.id = ?
            """,
            (new_id,),
        ).fetchone()
        return jsonify(_comment_to_dict(row)), 201

    rows = db.execute(
        """
        SELECT c.id, c.body, c.page_number, c.created_at,
               c.clause, c.sub_clause, c.sub_sub_clause,
               u.display_name AS author_name, u.role AS author_role,
               u.delegation   AS author_delegation
        FROM comments c
        JOIN users u ON u.id = c.author_id
        WHERE c.document_id = ?
        ORDER BY c.created_at ASC
        """,
        (doc_id,),
    ).fetchall()
    return jsonify([_comment_to_dict(r) for r in rows])


@app.route("/documents/<int:doc_id>/comments/<int:comment_id>", methods=["DELETE"])
@login_required
def delete_comment(doc_id: int, comment_id: int):
    db = get_db()
    row = db.execute(
        "SELECT author_id FROM comments WHERE id = ? AND document_id = ?",
        (comment_id, doc_id),
    ).fetchone()
    if not row:
        abort(404)
    if row["author_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(403)
    db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    db.commit()
    return "", 204


def _comment_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "body": row["body"],
        "page_number": row["page_number"],
        "clause": row["clause"] if "clause" in row.keys() else None,
        "sub_clause": row["sub_clause"] if "sub_clause" in row.keys() else None,
        "sub_sub_clause": row["sub_sub_clause"] if "sub_sub_clause" in row.keys() else None,
        "created_at": row["created_at"],
        "author_name": row["author_name"],
        "author_role": row["author_role"],
        "author_delegation": row["author_delegation"] if "author_delegation" in row.keys() else None,
    }


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------
@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    db = get_db()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        display_name = (request.form.get("display_name") or "").strip()
        participant_name = (request.form.get("participant_name") or "").strip()
        password = request.form.get("password") or ""
        role = request.form.get("role") or ""
        committee = (request.form.get("committee") or "").strip() or None
        delegation = (request.form.get("delegation") or "").strip() or None
        chair_position = (request.form.get("chair_position") or "").strip() or None
        advisor_school = (request.form.get("advisor_school") or "").strip() or None

        # Only delegates may have a country assigned. Drop any incoming value
        # for other roles so admins can't slip one in via the wire.
        if role != "delegate":
            delegation = None
        # Committee only applies to delegate / chair.
        if role not in ("delegate", "chair"):
            committee = None

        def _fail(msg, code=400):
            if _wants_json():
                return jsonify({"ok": False, "error": msg}), code
            flash(msg, "error")
            return None  # fall through to re-render

        err_resp = None
        if role not in VALID_ROLES:
            err_resp = _fail("Invalid role.")
        elif role != "admin" and not participant_name:
            # Admin is auto-named; everyone else requires a participant name.
            err_resp = _fail("Participant name is required (used on certificates).")
        elif len(password) < 8:
            err_resp = _fail("Password must be at least 8 characters.")
        elif committee and committee not in _cfg_committees():
            err_resp = _fail("Invalid committee.")
        elif role == "delegate":
            # Delegates are auto-named: username "del-<committee>-<iso3>" and
            # display name "<COMMITTEE> - <ISO3>". Admins don't type these.
            if not committee:
                err_resp = _fail("Delegates must be assigned a committee.")
            elif not delegation:
                err_resp = _fail("Delegates must be assigned a country.")
            else:
                code = country_iso3(delegation)
                if not code:
                    err_resp = _fail("Unrecognised country for that delegation.")
                else:
                    username = f"del-{committee.lower()}-{code.lower()}"
                    display_name = f"{committee} - {code}"
        elif role == "chair":
            # Chairs are auto-named by committee + position:
            #   president          → pres-<committee>          / "PRES - <COMMITTEE>"
            #   deputy president 1 → dpres-1-<committee>       / "DPRES 1 - <COMMITTEE>"
            #   deputy president 2 → dpres-2-<committee>       / "DPRES 2 - <COMMITTEE>"
            if not committee:
                err_resp = _fail("Chairs must be assigned a committee.")
            elif chair_position not in ("president", "deputy_1", "deputy_2"):
                err_resp = _fail("Pick a chair position.")
            else:
                c_lower = committee.lower()
                if chair_position == "president":
                    username = f"pres-{c_lower}"
                    display_name = f"PRES - {committee}"
                else:
                    n = "1" if chair_position == "deputy_1" else "2"
                    username = f"dpres-{n}-{c_lower}"
                    display_name = f"DPRES {n} - {committee}"
        elif role == "advisor":
            # Advisors are auto-named by school: adv-<code> / "ADV - <CODE>".
            if not advisor_school:
                if not _cfg_schools():
                    err_resp = _fail("No schools configured yet — add them in app.py _cfg_schools().")
                else:
                    err_resp = _fail("Advisors must be assigned a school.")
            elif advisor_school not in _cfg_schools():
                err_resp = _fail("Unrecognised school for that advisor.")
            else:
                code = _cfg_schools()[advisor_school]
                username = f"adv-{code.lower()}"
                display_name = f"ADV - {code}"
        elif role == "admin":
            # Admins are auto-named by sequence: pick the smallest N >= 1 such
            # that "admin-N" is not already taken. The seed "admin" username is
            # left alone.
            n = 1
            while db.execute(
                "SELECT 1 FROM users WHERE username = ?", (f"admin-{n}",)
            ).fetchone():
                n += 1
            username = f"admin-{n}"
            display_name = f"ADMIN {n}"
        elif role == "exec_gc":
            # EXEC/GC users are named from the participant name entered by the admin
            # (latin-alphabet slug, e.g. "can-dagtekin").
            username = f"exec-{participant_name}"
            display_name = f"EXEC/GC - {participant_name}"

        # Reject duplicate usernames up front with a clear message.
        if err_resp is None and db.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone():
            if role == "delegate":
                err_resp = _fail(
                    f"A delegate already exists for {committee} – {delegation} "
                    f"(username '{username}')."
                )
            elif role == "chair":
                if chair_position == "president":
                    err_resp = _fail(f"{committee} already has a President.")
                else:
                    n = "1" if chair_position == "deputy_1" else "2"
                    err_resp = _fail(f"{committee} already has Deputy President {n}.")
            elif role == "advisor":
                err_resp = _fail(f"An advisor already exists for {advisor_school}.")
            else:
                err_resp = _fail(f"Username '{username}' is already taken.")

        if err_resp is None:
            # Admin doesn't take a typed participant name; fall back to display name.
            stored_participant = participant_name or display_name
            try:
                cur = db.execute(
                    """
                    INSERT INTO users (username, display_name, participant_name,
                                       password_hash, role, committee, delegation)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (username, display_name, stored_participant,
                     hash_password(password), role, committee, delegation),
                )
                db.commit()
                new_id = cur.lastrowid
                if _wants_json():
                    row = db.execute(
                        """SELECT id, username, display_name, participant_name,
                                  role, committee, delegation, created_at
                           FROM users WHERE id = ?""",
                        (new_id,),
                    ).fetchone()
                    return jsonify({
                        "ok": True,
                        "user": {
                            "id": row["id"],
                            "username": row["username"],
                            "display_name": row["display_name"],
                            "participant_name": row["participant_name"],
                            "role": row["role"],
                            "committee": row["committee"],
                            "delegation": row["delegation"],
                            "created_at": row["created_at"],
                            "doc_count": 0,
                        },
                    })
                flash(f"Created user '{username}'.", "success")
                return redirect(url_for("admin_users"))
            except Exception as exc:
                err_resp = _fail(f"Could not create user: {exc}")

        if err_resp is not None:
            return err_resp

    users = db.execute(
        """
        SELECT u.id, u.username, u.display_name, u.participant_name,
               u.email, u.phone, u.role, u.committee, u.delegation, u.created_at,
               (SELECT COUNT(*) FROM documents d WHERE d.uploader_id = u.id) AS doc_count
        FROM users u
        ORDER BY u.created_at DESC
        """
    ).fetchall()
    # Compute the next-available "admin-N" and "exec-N" numbers so the create
    # form can preview their auto-names instantly.
    n_admin = 1
    while db.execute("SELECT 1 FROM users WHERE username = ?", (f"admin-{n_admin}",)).fetchone():
        n_admin += 1
    n_exec = 1
    while db.execute("SELECT 1 FROM users WHERE username = ?", (f"exec-{n_exec}",)).fetchone():
        n_exec += 1
    return render_template("admin/users.html", users=users, committees=_cfg_committees(),
                           country_iso3=COUNTRY_ISO3, schools=_cfg_schools(),
                           next_admin_n=n_admin, next_exec_n=n_exec)


@app.route("/admin/users/<int:user_id>/assign", methods=["POST"])
@admin_required
def admin_assign_committee(user_id: int):
    committee = (request.form.get("committee") or "").strip() or None
    delegation = (request.form.get("delegation") or "").strip() or None
    if committee and committee not in _cfg_committees():
        if _wants_json():
            return jsonify({"ok": False, "error": "Invalid committee."}), 400
        flash("Invalid committee.", "error")
        return redirect(url_for("admin_users"))
    db = get_db()
    db.execute(
        "UPDATE users SET committee = ?, delegation = ? WHERE id = ?",
        (committee, delegation, user_id),
    )
    db.commit()
    if _wants_json():
        return jsonify({
            "ok": True,
            "user_id": user_id,
            "committee": committee,
            "delegation": delegation,
        })
    flash("Assignment updated.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/advisor", methods=["GET", "POST"])
@admin_required
def admin_advisor_assignments(user_id: int):
    """Manage which (country, committee) pairs an advisor reviews."""
    db = get_db()
    advisor = db.execute(
        "SELECT id, username, display_name, participant_name, role FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not advisor or advisor["role"] != "advisor":
        flash("That user isn't an advisor.", "error")
        return redirect(url_for("admin_users"))

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "add":
            country = (request.form.get("country") or "").strip()
            committee = (request.form.get("committee") or "").strip()
            if not country:
                flash("Pick a country.", "error")
            elif committee not in _cfg_committees():
                flash("Pick a committee.", "error")
            else:
                try:
                    db.execute(
                        """INSERT INTO advisor_assignments (advisor_id, country, committee)
                           VALUES (?, ?, ?)""",
                        (user_id, country, committee),
                    )
                    db.commit()
                    flash(f"Added {country} – {committee}.", "success")
                except sqlite3.IntegrityError:
                    flash("That assignment already exists.", "error")
        elif action == "remove":
            assignment_id = request.form.get("assignment_id", type=int)
            db.execute(
                "DELETE FROM advisor_assignments WHERE id = ? AND advisor_id = ?",
                (assignment_id, user_id),
            )
            db.commit()
            flash("Assignment removed.", "success")
        return redirect(url_for("admin_advisor_assignments", user_id=user_id))

    assignments = db.execute(
        """SELECT id, country, committee, created_at
           FROM advisor_assignments WHERE advisor_id = ?
           ORDER BY country, committee""",
        (user_id,),
    ).fetchall()
    return render_template(
        "admin/advisor_assignments.html",
        advisor=advisor,
        assignments=assignments,
        committees=_cfg_committees(),
    )


@app.route("/admin/users/<int:user_id>/reset", methods=["POST"])
@admin_required
def admin_reset_password(user_id: int):
    password = request.form.get("password") or ""
    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return redirect(url_for("admin_users"))
    db = get_db()
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(password), user_id),
    )
    db.commit()
    # Invalidate active sessions for that user so they have to log in again.
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.commit()
    flash("Password reset and active sessions revoked.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id: int):
    if user_id == g.user["id"]:
        if _wants_json():
            return jsonify({"ok": False, "error": "You can't delete your own account."}), 400
        flash("You can't delete your own account.", "error")
        return redirect(url_for("admin_users"))
    db = get_db()
    try:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    except Exception as exc:
        if _wants_json():
            return jsonify({
                "ok": False,
                "error": f"Could not delete user (they may have uploaded documents): {exc}",
            }), 400
        flash(f"Could not delete user (they may have uploaded documents): {exc}", "error")
        return redirect(url_for("admin_users"))
    if _wants_json():
        return jsonify({"ok": True, "user_id": user_id})
    flash("User deleted.", "success")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
# Admin: dynamic configurations page
# ---------------------------------------------------------------------------
@app.route("/admin/config", methods=["GET"])
@roles_required("exec_gc")
def admin_config():
    cfg = _load_config()
    # Group existing chair users by committee + position for the roster view.
    db = get_db()
    chairs = db.execute(
        """SELECT id, username, display_name, participant_name, committee
           FROM users WHERE role = 'chair'
           ORDER BY committee, username"""
    ).fetchall()
    roster = {}
    for c in cfg.get("committees", []):
        roster[c["code"]] = {"president": None, "deputy_1": None, "deputy_2": None}
    for row in chairs:
        com = row["committee"]
        u = row["username"] or ""
        if com not in roster:
            continue
        slot = None
        if u == f"pres-{com.lower()}":     slot = "president"
        elif u == f"dpres-1-{com.lower()}": slot = "deputy_1"
        elif u == f"dpres-2-{com.lower()}": slot = "deputy_2"
        if slot:
            roster[com][slot] = {
                "id": row["id"], "username": row["username"],
                "participant_name": row["participant_name"] or "",
                "display_name": row["display_name"],
            }
    return render_template("admin/config.html", cfg=cfg, roster=roster)


@app.route("/admin/config/schools", methods=["POST"])
@admin_required
def admin_config_schools():
    """Replace the schools list. Form posts pairs of name[]/code[] inputs."""
    names = request.form.getlist("school_name[]")
    codes = request.form.getlist("school_code[]")
    schools = {}
    for name, code in zip(names, codes):
        n, c = name.strip(), code.strip().upper()
        if not n or not c:
            continue
        if not c.replace("-", "").isalnum():
            flash(f"Invalid school code '{c}' — letters/digits only.", "error")
            return redirect(url_for("admin_config"))
        if n in schools:
            flash(f"Duplicate school name '{n}'.", "error")
            return redirect(url_for("admin_config"))
        schools[n] = c
    cfg = _load_config(); cfg["schools"] = schools; _store_config(cfg)
    flash(f"Saved {len(schools)} school{'s' if len(schools) != 1 else ''}.", "success")
    return redirect(url_for("admin_config"))


@app.route("/admin/config/committees", methods=["POST"])
@admin_required
def admin_config_committees():
    """Replace committees list & per-committee agenda items."""
    codes = request.form.getlist("committee_code[]")
    agendas = request.form.getlist("committee_agenda[]")
    if len(codes) != len(agendas):
        flash("Form data was malformed.", "error")
        return redirect(url_for("admin_config"))
    new_committees = []
    seen = set()
    for code, agenda_block in zip(codes, agendas):
        code = code.strip().upper()
        if not code:
            continue
        if not code.replace("-", "").isalnum():
            flash(f"Invalid committee code '{code}'.", "error")
            return redirect(url_for("admin_config"))
        if code in seen:
            flash(f"Duplicate committee code '{code}'.", "error")
            return redirect(url_for("admin_config"))
        seen.add(code)
        items = [line.strip() for line in (agenda_block or "").splitlines() if line.strip()]
        new_committees.append({"code": code, "agenda_items": items})
    cfg = _load_config(); cfg["committees"] = new_committees; _store_config(cfg)
    flash("Committees and agenda items saved.", "success")
    return redirect(url_for("admin_config"))


@app.route("/admin/config/chair/<int:user_id>", methods=["POST"])
@admin_required
def admin_config_chair_name(user_id: int):
    """Update the chair user's participant_name from the roster row."""
    name = (request.form.get("participant_name") or "").strip()
    if not name:
        flash("Participant name cannot be empty.", "error")
        return redirect(url_for("admin_config"))
    db = get_db()
    row = db.execute(
        "SELECT id, role, display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row or row["role"] != "chair":
        flash("That user is not a chair.", "error")
        return redirect(url_for("admin_config"))
    db.execute("UPDATE users SET participant_name = ? WHERE id = ?", (name, user_id))
    db.commit()
    flash(f"Updated {row['display_name']}'s participant name.", "success")
    return redirect(url_for("admin_config"))


@app.route("/admin/config/conference", methods=["POST"])
@admin_required
def admin_config_conference():
    """Update conference info + upload-permission duration."""
    loc = (request.form.get("location") or "").strip()
    email = (request.form.get("secretariat_email") or "").strip()
    url = (request.form.get("external_website_url") or "").strip()
    try:
        minutes = int(request.form.get("upload_permission_minutes") or "0")
    except (TypeError, ValueError):
        minutes = 0
    if minutes < 1 or minutes > 240:
        flash("Upload window must be between 1 and 240 minutes.", "error")
        return redirect(url_for("admin_config"))
    cfg = _load_config()
    cfg["conference"] = {"location": loc, "secretariat_email": email, "external_website_url": url}
    cfg["upload_permission_minutes"] = minutes
    _store_config(cfg)
    flash("Conference info saved.", "success")
    return redirect(url_for("admin_config"))


@app.route("/admin/config/schedule", methods=["POST"])
@admin_required
def admin_config_schedule():
    """Replace the schedule. Each day is one textarea where each line is
    'TIME | Label' (e.g. '09:30 – 10:00 | Buses arrive')."""
    day_titles = request.form.getlist("day_title[]")
    day_blocks = request.form.getlist("day_items[]")
    if len(day_titles) != len(day_blocks):
        flash("Form data was malformed.", "error")
        return redirect(url_for("admin_config"))
    schedule = []
    for title, block in zip(day_titles, day_blocks):
        title = title.strip()
        if not title:
            continue
        items = []
        for line in (block or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                time_part, label = line.split("|", 1)
                items.append([time_part.strip(), label.strip()])
            else:
                items.append([line, ""])
        schedule.append({"day": title, "items": items})
    cfg = _load_config(); cfg["schedule"] = schedule; _store_config(cfg)
    flash("Schedule saved.", "success")
    return redirect(url_for("admin_config"))


# ---------------------------------------------------------------------------
# Admin "Sign in as" (impersonation)
# ---------------------------------------------------------------------------
@app.route("/admin/users/<int:user_id>/impersonate", methods=["POST"])
@admin_required
def admin_impersonate(user_id: int):
    """Let an admin sign in as another user. The admin's own session token is
    stashed in the signed Flask session cookie so they can return with one
    click. Only admins reach here, so nested impersonation can't occur."""
    if user_id == g.user["id"]:
        flash("You're already signed in as yourself.", "error")
        return redirect(url_for("admin_users"))

    db = get_db()
    target = db.execute(
        "SELECT id, username, display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin_users"))

    admin_token = request.cookies.get(SESSION_COOKIE)
    # Mint a fresh session for the target user and switch the cookie to it.
    token = create_session(user_id)
    session["impersonator_token"] = admin_token
    session["impersonator_name"] = g.user["display_name"]
    session["impersonator_id"] = g.user["id"]

    resp = redirect(url_for("dashboard"))
    resp.set_cookie(
        SESSION_COOKIE, token,
        httponly=True, samesite="Lax", max_age=7 * 24 * 3600,
    )
    flash(
        f"You are now signed in as {target['display_name']} "
        f"(@{target['username']}).",
        "success",
    )
    return resp


@app.route("/impersonate/stop", methods=["POST"])
@login_required
def impersonate_stop():
    """Return to the admin account that started an impersonation."""
    admin_token = session.get("impersonator_token")
    if not admin_token:
        flash("You're not signed in as another user.", "error")
        return redirect(url_for("dashboard"))

    # Tear down the temporary impersonation session.
    current = request.cookies.get(SESSION_COOKIE)
    if current and current != admin_token:
        delete_session(current)

    session.pop("impersonator_token", None)
    session.pop("impersonator_name", None)
    session.pop("impersonator_id", None)

    resp = redirect(url_for("admin_users"))
    resp.set_cookie(
        SESSION_COOKIE, admin_token,
        httponly=True, samesite="Lax", max_age=7 * 24 * 3600,
    )
    flash("Returned to your admin account.", "success")
    return resp


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
@app.errorhandler(403)
def err_403(e):
    return render_template("error.html", code=403, message=str(e.description or "Forbidden")), 403


@app.errorhandler(404)
def err_404(e):
    return render_template("error.html", code=404, message="Not found"), 404


@app.errorhandler(413)
def err_413(e):
    return render_template("error.html", code=413,
                           message=f"File too large (max {MAX_UPLOAD_MB} MB)"), 413


if __name__ == "__main__":
    # Bind to 0.0.0.0 to allow LAN access; IP allowlist gates who can connect.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
