CREATE TABLE IF NOT EXISTS roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
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
    exec_role_id             INTEGER REFERENCES roles(id) ON DELETE SET NULL,
    notes_last_seen_at       TEXT,
    amendments_last_seen_at  TEXT,
    resolutions_last_seen_at TEXT,
    outside_since            TEXT,
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exec_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id      INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    notes        TEXT,
    due_date     TEXT NOT NULL,
    priority     TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    status       TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_exec_tasks_role ON exec_tasks(role_id, due_date);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    description  TEXT,
    filename     TEXT,                            -- optional PDF (Google Doc is primary)
    stored_name  TEXT UNIQUE,
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    committee    TEXT,
    agenda_item  TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending, debated, passed, failed
    is_summit    INTEGER NOT NULL DEFAULT 0,       -- 1 = promoted to International Summit
    approved     INTEGER NOT NULL DEFAULT 1,       -- 0 = awaiting chair approval
    approved_at  TEXT,
    approved_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    voting_status TEXT NOT NULL DEFAULT 'closed', -- closed, open, locked
    voting_locked_at TEXT,
    in_debate    INTEGER NOT NULL DEFAULT 0,      -- 1 = chair marked as in debate (visible to delegates)
    body_text    TEXT,                            -- editable working text (chair can edit)
    body_updated_at TEXT,
    body_updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    google_doc_url TEXT,                           -- optional live Google Doc embed
    uploader_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS votes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    voter_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    choice      TEXT NOT NULL CHECK (choice IN ('for', 'against')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(document_id, voter_id)
);
CREATE INDEX IF NOT EXISTS idx_votes_doc ON votes(document_id);
-- The unique partial index on (committee) WHERE is_summit = 1 is created in
-- lib/db.py:_migrate so it runs AFTER the column has been ensured on
-- pre-existing databases.

CREATE INDEX IF NOT EXISTS idx_documents_uploader ON documents(uploader_id);
CREATE INDEX IF NOT EXISTS idx_documents_created  ON documents(created_at DESC);

CREATE TABLE IF NOT EXISTS comments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    author_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    page_number    INTEGER,
    clause         TEXT,
    sub_clause     TEXT,
    sub_sub_clause TEXT,
    body           TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_comments_document ON comments(document_id, created_at);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS notes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sender_delegation     TEXT,
    committee             TEXT NOT NULL,
    recipient_delegation  TEXT NOT NULL,
    body                  TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notes_committee ON notes(committee, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_recipient ON notes(committee, recipient_delegation, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_sender ON notes(sender_id);

CREATE TABLE IF NOT EXISTS tally_resets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    committee    TEXT NOT NULL,
    performed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    performed_at TEXT NOT NULL DEFAULT (datetime('now')),
    entry_count  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tally_resets_committee ON tally_resets(committee, performed_at DESC);

CREATE TABLE IF NOT EXISTS tally_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    committee   TEXT NOT NULL,
    delegation  TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('poi', 'speech', 'amendment')),
    points      INTEGER NOT NULL,
    recorded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reset_id    INTEGER REFERENCES tally_resets(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tally_committee ON tally_entries(committee, delegation);
CREATE INDEX IF NOT EXISTS idx_tally_created   ON tally_entries(created_at DESC);
-- The partial index on (committee) WHERE reset_id IS NULL is created in
-- lib/db.py:_migrate so it runs after reset_id is guaranteed to exist.

CREATE TABLE IF NOT EXISTS advisor_assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    country     TEXT NOT NULL,
    committee   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(advisor_id, country, committee)
);
CREATE INDEX IF NOT EXISTS idx_advisor_assignments ON advisor_assignments(advisor_id);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT,
    subject     TEXT,
    body        TEXT NOT NULL,
    sender_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
