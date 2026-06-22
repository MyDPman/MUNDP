"""Create the first admin user. Run once after install:

    python3 seed.py

Will prompt for username, display name, and password.
"""
import getpass
import sqlite3
import sys

from lib.auth import hash_password
from lib.db import DB_PATH, init_db


def main() -> int:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    existing_admin = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE role = 'admin'"
    ).fetchone()["n"]
    if existing_admin > 0:
        print(f"An admin already exists ({existing_admin} found). Aborting.")
        print("Use the /admin/users page in the running app to add more users.")
        return 1

    print("Creating the initial admin user.")
    username = input("Username: ").strip().lower()
    display_name = input("Display name: ").strip()
    password = getpass.getpass("Password (min 8 chars): ")
    confirm = getpass.getpass("Confirm password: ")

    if not username or not display_name:
        print("Username and display name are required.")
        return 1
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return 1
    if password != confirm:
        print("Passwords do not match.")
        return 1

    try:
        conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role)
            VALUES (?, ?, ?, 'admin')
            """,
            (username, display_name, hash_password(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        print(f"User '{username}' already exists.")
        return 1

    print(f"\nAdmin '{username}' created. Start the app and sign in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
