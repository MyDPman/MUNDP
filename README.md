# MUNDP Portal

A network-restricted document review portal. Uploaders post PDFs, reviewers comment, admins manage users.

## Stack

- Flask + SQLite (zero external services)
- bcrypt password hashing, server-side sessions in DB
- PDF.js (loaded from CDN) for in-browser PDF viewing
- IP allowlist middleware so only configured networks can connect

## Quick start (Mac, local prototype)

```bash
cd /Users/can/Desktop/MUNDP

# 1. Create a virtual env and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment (copy and edit)
cp .env.example .env
# Edit .env: set SECRET_KEY to a random long string

# 3. Create the first admin user
python3 seed.py

# 4. Run the dev server
python3 app.py
```

Open <http://127.0.0.1:5000> and sign in with the admin credentials you just created.

> **macOS note:** AirPlay Receiver also listens on port 5000. If you see odd 403s, either disable AirPlay Receiver (System Settings → General → AirDrop & Handoff) or run the app on another port: `PORT=5050 python3 app.py`.

## Roles

| Role     | Can view | Can comment | Can upload | Manage users |
|----------|----------|-------------|------------|--------------|
| admin    | ✓        | ✓           | ✓          | ✓            |
| uploader | ✓        | ✓           | ✓          |              |
| reviewer | ✓        | ✓           |            |              |

Admin creates all accounts and sets passwords via `/admin/users`. Users cannot self-register.

## Network restriction

The app rejects any request whose source IP doesn't match a prefix in `ALLOWED_IP_PREFIXES` (set in `.env`).

```
ALLOWED_IP_PREFIXES=127.0.0.1,::1               # dev: localhost only (default)
ALLOWED_IP_PREFIXES=192.168.1.,10.0.0.          # LAN subnets
```

Match is by string-prefix on the IP, so `192.168.1.` covers `192.168.1.0`–`192.168.1.255`.

> ⚠️ The allowlist trusts the direct peer address. If you put the app behind a reverse proxy (nginx, Caddy), either remove the proxy's IP from the allowlist and configure the proxy to enforce the restriction, or change `lib/network.py` to consult `X-Forwarded-For` from a trusted proxy.

## Deploying to a LAN server (production sketch)

For ~400 users, an Ubuntu LTS box on your LAN is plenty.

1. Install Python 3.10+ and `pip`.
2. Copy this repo onto the server, `pip install -r requirements.txt` plus `gunicorn`.
3. Set `.env`:
    ```
    SECRET_KEY=<long random string>
    ALLOWED_IP_PREFIXES=<your LAN subnets>
    MAX_UPLOAD_MB=50
    ```
4. Run under gunicorn:
    ```bash
    gunicorn -w 4 -b 0.0.0.0:5000 app:app
    ```
5. Put it behind nginx for TLS (self-signed cert is fine on LAN), and configure nginx to:
    - bind only to the LAN-facing interface
    - block the WAN-facing interface at the firewall too (defense in depth)
6. Back up `data/app.db` and `uploads/` regularly.

## Layout

```
app.py                  # Flask app + all routes
schema.sql              # DB schema (runs on first start)
seed.py                 # Create initial admin
lib/
    db.py               # SQLite connection helpers
    auth.py             # Password hashing, session creation
    decorators.py       # @login_required, @admin_required, @roles_required
    network.py          # IP-allowlist middleware
templates/              # Jinja2 templates
static/                 # CSS + viewer JS
data/app.db             # SQLite DB (created on first run)
uploads/                # PDF files (one per document)
```

## Security notes

- Passwords are bcrypt-hashed. Plain passwords are only seen during login submit.
- Sessions are server-side (rows in `sessions` table) with httpOnly + SameSite=Lax cookies.
- **CSRF**: synchronizer token stored in Flask's signed session cookie. HTML forms include a hidden `csrf_token` input; JSON requests send `X-CSRF-Token` header. Validated on every unsafe method.
- **Login rate-limit**: 5 failed attempts per (username, IP) per 15 min → 15-min lockout. In-memory; resets on restart.
- **Open-redirect** on `?next=` is prevented (only relative paths accepted).
- Admin password reset revokes all active sessions for that user.
- Uploads are restricted to `.pdf` extension and a `%PDF-` magic-byte check.
- Files are served as inline PDFs by Flask using the original filename for download.
- All routes (except `/login`) require authentication; the network allowlist applies to every request including the login page.

## Features

| Feature | Who can do it |
|---------|---------------|
| Sign in / sign out | Everyone with an account |
| View document list (with search filter) | All roles |
| Open a PDF + view comments | All roles |
| Add comment (optionally tagged with current page) | All roles |
| Click a comment's page badge to jump to that page | All roles |
| Delete own comments | Author + admin |
| Upload a PDF | uploader + admin |
| Delete a document | Original uploader + admin |
| Create / reset / delete users | admin |

## Known limitations / future work

- No PDF text-search or inline annotation overlay yet — comments are tagged with a page number but rendered in the side panel only.
- No user-facing password reset (admin must reset).
- Rate-limit state is in-memory; if you scale to multiple workers/hosts, move it to Redis.
- SQLite is fine for hundreds of users; if you outgrow it, swap to Postgres via small changes in `lib/db.py`.
