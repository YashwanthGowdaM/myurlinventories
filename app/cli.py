"""Admin CLI. Usage (inside the container):

    python -m app.cli create-user <username> [--force]
    python -m app.cli delete-user <username>
    python -m app.cli list-users
"""
import argparse
import getpass
import sys

import pyotp
import segno
from argon2 import PasswordHasher

from . import create_app
from .db import get_db

ISSUER = "urls.yashwanthgowdam.in"


def _prompt_password():
    pw = getpass.getpass("Password (min 12 chars): ")
    if len(pw) < 12 or len(pw) > 256:
        sys.exit("Password must be between 12 and 256 characters.")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return pw


def create_user(username, force):
    db = get_db()
    exists = db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    if exists and not force:
        sys.exit(f"User {username!r} exists. Use --force to reset password and MFA.")
    pw_hash = PasswordHasher().hash(_prompt_password())
    secret = pyotp.random_base32()
    if exists:
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
    uri = pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)
    print("\nScan this QR code with your authenticator app:\n")
    segno.make(uri).terminal(compact=True)
    print(f"\nManual entry key: {secret}\n(Clear your terminal scrollback afterwards.)")


def main():
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("username")
    c.add_argument("--force", action="store_true")
    d = sub.add_parser("delete-user")
    d.add_argument("username")
    sub.add_parser("list-users")
    args = parser.parse_args()

    with create_app().app_context():
        if args.cmd == "create-user":
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
