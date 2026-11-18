"""Admin CLI (run inside the container).

    python -m app.cli ensure-admin        # non-interactive, used by the deploy workflow
    python -m app.cli create-user NAME [--force]
    python -m app.cli delete-user NAME
    python -m app.cli list-users
"""
import argparse
import getpass
import os
import re
import sys

import pyotp
import segno
from argon2 import PasswordHasher

from . import create_app
from .db import get_db

ISSUER = "urls.yashwanthgowdam.in"
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")


def _check_username(username):
    if not USERNAME_RE.match(username):
        sys.exit("Username must be 3-64 characters: letters, digits, dot, underscore, hyphen.")


def _check_password(password):
    if not 12 <= len(password) <= 256:
        sys.exit("Password must be between 12 and 256 characters.")


def _exists(username):
    return get_db().execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()


def _store(username, password):
    """Create or overwrite the user with a fresh password hash and a new TOTP secret."""
    db = get_db()
    pw_hash = PasswordHasher().hash(password)
    secret = pyotp.random_base32()
    if _exists(username):
        db.execute(
            "UPDATE users SET password_hash=?, totp_secret=?, last_totp_step=0 WHERE username=?",
            (pw_hash, secret, username),
        )
    else:
        db.execute(
            "INSERT INTO users(username, password_hash, totp_secret) VALUES (?, ?, ?)",
            (username, pw_hash, secret),
        )
    db.commit()
    return secret


def _show_enrolment(username, secret, qr):
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)
    print("\n=== Authenticator setup ===")
    if qr:
        segno.make(uri).terminal(compact=True)
    print(f"Account : {username}")
    print(f"Key     : {secret}")
    print("Type    : time-based (TOTP), 6 digits, 30 seconds")
    print(f"URI     : {uri}")
    print("In your app choose 'Add account' > 'Enter a setup key' and type the key above.")


def create_user(username, force):
    _check_username(username)
    if _exists(username) and not force:
        sys.exit(f"User {username!r} exists. Use --force to reset password and MFA.")
    password = getpass.getpass("Password (min 12 chars): ")
    _check_password(password)
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    _show_enrolment(username, _store(username, password), qr=True)


def ensure_admin():
    username = (os.environ.get("ADMIN_USERNAME") or "").strip()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    reset = os.environ.get("RESET_ADMIN") == "1"
    if not username or not password:
        print("ADMIN_USERNAME / ADMIN_PASSWORD not set: skipping admin creation.")
        return
    _check_username(username)
    _check_password(password)
    if _exists(username) and not reset:
        print("Admin account already exists: nothing to do.")
        return
    print("Resetting admin password and MFA." if _exists(username) else "Creating admin account.")
    _show_enrolment(username, _store(username, password), qr=False)


def main():
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ensure-admin")
    c = sub.add_parser("create-user")
    c.add_argument("username")
    c.add_argument("--force", action="store_true")
    d = sub.add_parser("delete-user")
    d.add_argument("username")
    sub.add_parser("list-users")
    args = parser.parse_args()

    with create_app().app_context():
        if args.cmd == "ensure-admin":
            ensure_admin()
        elif args.cmd == "create-user":
            create_user(args.username, args.force)
        elif args.cmd == "delete-user":
            db = get_db()
            cur = db.execute("DELETE FROM users WHERE username = ?", (args.username,))
            db.commit()
            print("Deleted." if cur.rowcount else "No such user.")
        else:
            for row in get_db().execute("SELECT username, created_at FROM users ORDER BY id"):
                print(f"{row['username']}\t{row['created_at']}")


if __name__ == "__main__":
    main()
