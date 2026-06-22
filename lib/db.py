import os
import sqlite3
from flask import g

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent migrations for older DBs."""
    # 1. Add documents.committee + documents.status if missing
    doc_cols = [r["name"] for r in conn.execute("PRAGMA table_info(documents)").fetchall()]
    if "committee" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN committee TEXT")
    if "status" not in doc_cols:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )
    if "agenda_item" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN agenda_item TEXT")
    if "approved" not in doc_cols:
        # Default to 1 so existing rows stay publicly visible after migration.
        conn.execute("ALTER TABLE documents ADD COLUMN approved INTEGER NOT NULL DEFAULT 1")
    if "approved_at" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN approved_at TEXT")
        # Existing rows: treat them as approved at their original upload time.
        conn.execute("UPDATE documents SET approved_at = created_at WHERE approved = 1 AND approved_at IS NULL")
    if "approved_by" not in doc_cols:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL"
        )
    if "voting_status" not in doc_cols:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN voting_status TEXT NOT NULL DEFAULT 'closed'"
        )
    if "voting_locked_at" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN voting_locked_at TEXT")
    if "body_text" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN body_text TEXT")
    if "body_updated_at" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN body_updated_at TEXT")
    if "body_updated_by" not in doc_cols:
        conn.execute(
            "ALTER TABLE documents ADD COLUMN body_updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL"
        )
    if "google_doc_url" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN google_doc_url TEXT")
    if "in_debate" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN in_debate INTEGER NOT NULL DEFAULT 0")

    # 1f. Rebuild documents to allow nullable filename/stored_name (Google Doc
    #     URL is now mandatory; the PDF is optional).
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    old_sql = (row["sql"] if row else "") or ""
    if "filename     TEXT NOT NULL" in old_sql or "filename TEXT NOT NULL" in old_sql:
        conn.executescript("""
            CREATE TABLE documents_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT NOT NULL,
                description  TEXT,
                filename     TEXT,
                stored_name  TEXT UNIQUE,
                size_bytes   INTEGER NOT NULL DEFAULT 0,
                committee    TEXT,
                agenda_item  TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                is_summit    INTEGER NOT NULL DEFAULT 0,
                approved     INTEGER NOT NULL DEFAULT 1,
                approved_at  TEXT,
                approved_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                voting_status TEXT NOT NULL DEFAULT 'closed',
                voting_locked_at TEXT,
                body_text    TEXT,
                body_updated_at TEXT,
                body_updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                google_doc_url TEXT,
                uploader_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO documents_new (id, title, description, filename, stored_name,
                                       size_bytes, committee, agenda_item, status, is_summit,
                                       approved, approved_at, approved_by, voting_status,
                                       voting_locked_at, body_text, body_updated_at, body_updated_by,
                                       google_doc_url, uploader_id, created_at)
            SELECT id, title, description, filename, stored_name,
                   size_bytes, committee, agenda_item, status, is_summit,
                   approved, approved_at, approved_by, voting_status,
                   voting_locked_at, body_text, body_updated_at, body_updated_by,
                   google_doc_url, uploader_id, created_at
            FROM documents;
            DROP TABLE documents;
            ALTER TABLE documents_new RENAME TO documents;
            CREATE INDEX IF NOT EXISTS idx_documents_uploader ON documents(uploader_id);
            CREATE INDEX IF NOT EXISTS idx_documents_created  ON documents(created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_summit_per_committee
                ON documents(committee) WHERE is_summit = 1;
        """)

    # 1e. Add comment location columns
    com_cols = [r["name"] for r in conn.execute("PRAGMA table_info(comments)").fetchall()]
    if "clause" not in com_cols:
        conn.execute("ALTER TABLE comments ADD COLUMN clause TEXT")
    if "sub_clause" not in com_cols:
        conn.execute("ALTER TABLE comments ADD COLUMN sub_clause TEXT")
    if "sub_sub_clause" not in com_cols:
        conn.execute("ALTER TABLE comments ADD COLUMN sub_sub_clause TEXT")

    # 1b. Rebuild documents if the status CHECK is the old (pending, debated) only.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    old_sql = (row["sql"] if row else "") or ""
    if "CHECK (status IN ('pending', 'debated'))" in old_sql or \
       "CHECK(status IN ('pending', 'debated'))" in old_sql:
        cols_now = [r["name"] for r in conn.execute("PRAGMA table_info(documents)").fetchall()]
        summit_select = "is_summit" if "is_summit" in cols_now else "0"
        conn.executescript(f"""
            CREATE TABLE documents_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT NOT NULL,
                description  TEXT,
                filename     TEXT NOT NULL,
                stored_name  TEXT NOT NULL UNIQUE,
                size_bytes   INTEGER NOT NULL,
                committee    TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                is_summit    INTEGER NOT NULL DEFAULT 0,
                uploader_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO documents_new (id, title, description, filename, stored_name,
                                       size_bytes, committee, status, is_summit,
                                       uploader_id, created_at)
            SELECT id, title, description, filename, stored_name,
                   size_bytes, committee, status, {summit_select},
                   uploader_id, created_at
            FROM documents;
            DROP TABLE documents;
            ALTER TABLE documents_new RENAME TO documents;
            CREATE INDEX IF NOT EXISTS idx_documents_uploader ON documents(uploader_id);
            CREATE INDEX IF NOT EXISTS idx_documents_created  ON documents(created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_summit_per_committee
                ON documents(committee) WHERE is_summit = 1;
        """)

    # 1c. If is_summit still missing (no rebuild needed), add it now.
    doc_cols = [r["name"] for r in conn.execute("PRAGMA table_info(documents)").fetchall()]
    if "is_summit" not in doc_cols:
        conn.execute("ALTER TABLE documents ADD COLUMN is_summit INTEGER NOT NULL DEFAULT 0")

    # 1d. Always ensure the partial unique index exists now that is_summit is guaranteed.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_summit_per_committee "
        "ON documents(committee) WHERE is_summit = 1"
    )

    # 2. Rebuild users table if its role CHECK still uses old names
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if row and "'chair'" not in (row["sql"] or ""):
        conn.executescript("""
            CREATE TABLE users_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                display_name  TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL CHECK (role IN ('admin', 'chair', 'delegate')),
                committee     TEXT,
                delegation    TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO users_new (id, username, display_name, password_hash, role, created_at)
            SELECT id, username, display_name, password_hash,
                   CASE role
                       WHEN 'uploader' THEN 'chair'
                       WHEN 'reviewer' THEN 'delegate'
                       ELSE role
                   END,
                   created_at
            FROM users;
            DROP TABLE users;
            ALTER TABLE users_new RENAME TO users;
        """)

    # 3. Add committee/delegation/last-seen columns to users if missing
    user_cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "committee" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN committee TEXT")
    if "delegation" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN delegation TEXT")
    if "notes_last_seen_at" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN notes_last_seen_at TEXT")
    if "amendments_last_seen_at" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN amendments_last_seen_at TEXT")
    if "resolutions_last_seen_at" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN resolutions_last_seen_at TEXT")
    if "outside_since" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN outside_since TEXT")

    # Extend the users.role CHECK to allow 'advisor' if it doesn't already
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    users_sql = (row["sql"] if row else "") or ""
    if "'advisor'" not in users_sql:
        # Rebuild the users table with the wider CHECK constraint, preserving
        # every column already present so we don't lose anything (committee,
        # delegation, last_seen timestamps, outside_since, participant_name,
        # email, phone, etc.).
        cols_now = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        all_cols = [
            "id", "username", "display_name", "password_hash", "role",
            "committee", "delegation", "notes_last_seen_at",
            "amendments_last_seen_at", "resolutions_last_seen_at",
            "outside_since", "participant_name", "email", "phone", "created_at",
        ]
        # Use only columns that exist now (older DBs might not have all of them)
        present_cols = [c for c in all_cols if c in cols_now]
        cols_list = ", ".join(present_cols)
        conn.executescript(f"""
            CREATE TABLE users_new (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                username                 TEXT NOT NULL UNIQUE,
                display_name             TEXT NOT NULL,
                participant_name         TEXT,
                email                    TEXT,
                phone                    TEXT,
                password_hash            TEXT NOT NULL,
                role                     TEXT NOT NULL CHECK (role IN ('admin', 'chair', 'delegate', 'advisor')),
                committee                TEXT,
                delegation               TEXT,
                notes_last_seen_at       TEXT,
                amendments_last_seen_at  TEXT,
                resolutions_last_seen_at TEXT,
                outside_since            TEXT,
                created_at               TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO users_new ({cols_list})
            SELECT {cols_list} FROM users;
            DROP TABLE users;
            ALTER TABLE users_new RENAME TO users;
        """)

    # 4. Tally reset support: tally_resets table + tally_entries.reset_id
    tally_cols = [r["name"] for r in conn.execute("PRAGMA table_info(tally_entries)").fetchall()]
    if "reset_id" not in tally_cols:
        conn.execute(
            "ALTER TABLE tally_entries ADD COLUMN reset_id INTEGER REFERENCES tally_resets(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tally_active ON tally_entries(committee) WHERE reset_id IS NULL"
    )
    if "participant_name" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN participant_name TEXT")
        # Backfill with display_name so existing accounts have a value to show.
        conn.execute("UPDATE users SET participant_name = display_name WHERE participant_name IS NULL")
    if "email" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "phone" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")

    # 5. Permission-based upload: chairs grant a 10-minute upload window to a
    #    delegate. Stored as an ISO-8601 UTC timestamp; NULL or past means no
    #    permission. Refresh user_cols since earlier rebuilds may have shifted.
    user_cols_now = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "upload_permission_until" not in user_cols_now:
        conn.execute("ALTER TABLE users ADD COLUMN upload_permission_until TEXT")

    # Extend the users.role CHECK to allow 'exec_gc' if it doesn't already.
    # Same rebuild pattern as the 'advisor' migration above.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    users_sql_now = (row["sql"] if row else "") or ""
    if "'exec_gc'" not in users_sql_now:
        cols_now = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        all_cols = [
            "id", "username", "display_name", "password_hash", "role",
            "committee", "delegation", "notes_last_seen_at",
            "amendments_last_seen_at", "resolutions_last_seen_at",
            "outside_since", "participant_name", "email", "phone",
            "upload_permission_until", "created_at",
        ]
        present_cols = [c for c in all_cols if c in cols_now]
        cols_list = ", ".join(present_cols)
        conn.executescript(f"""
            CREATE TABLE users_new (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                username                 TEXT NOT NULL UNIQUE,
                display_name             TEXT NOT NULL,
                participant_name         TEXT,
                email                    TEXT,
                phone                    TEXT,
                password_hash            TEXT NOT NULL,
                role                     TEXT NOT NULL CHECK (role IN ('admin', 'chair', 'delegate', 'advisor', 'exec_gc')),
                committee                TEXT,
                delegation               TEXT,
                notes_last_seen_at       TEXT,
                amendments_last_seen_at  TEXT,
                resolutions_last_seen_at TEXT,
                outside_since            TEXT,
                upload_permission_until  TEXT,
                created_at               TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO users_new ({cols_list})
            SELECT {cols_list} FROM users;
            DROP TABLE users;
            ALTER TABLE users_new RENAME TO users;
        """)

    # 6. Admin-editable dynamic configuration (committees, schools, schedule,
    #    conference metadata, upload-window duration). Single-row table holding
    #    a JSON blob — easy migrations, atomic writes.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            data        TEXT    NOT NULL,
            updated_at  TEXT,
            updated_by  INTEGER REFERENCES users(id) ON DELETE SET NULL
        )
    """)
