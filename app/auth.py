import re
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .db import get_db
from .security import check_csrf, current_user

bp = Blueprint("auth", __name__)

_ph = PasswordHasher()
_DUMMY_HASH = _ph.hash("timing-equalisation-only")  # keeps unknown-user timing close to real

WINDOW = 15 * 60
USER_LIMIT = 5
IP_LIMIT = 20
MFA_STEP_SECONDS = 30
MFA_PENDING_SECONDS = 5 * 60


# ---- throttling (stored in SQLite so it is shared across workers) ----------------------------
def _keys(username):
    return f"u:{username.lower()}", f"ip:{request.remote_addr}"


def _throttled(username):
    db = get_db()
    cutoff = int(time.time()) - WINDOW
    db.execute("DELETE FROM login_attempts WHERE at < ?", (cutoff,))
    user_key, ip_key = _keys(username)

    def count(key):
        return db.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE key = ? AND at >= ?", (key, cutoff)
        ).fetchone()[0]

    return count(user_key) >= USER_LIMIT or count(ip_key) >= IP_LIMIT


def _record_failure(username):
    db = get_db()
    now = int(time.time())
    for key in _keys(username):
        db.execute("INSERT INTO login_attempts(key, at) VALUES (?, ?)", (key, now))
    db.commit()
    current_app.logger.warning("auth.failure user=%r ip=%s", username, request.remote_addr)


def _clear_failures(username):
    db = get_db()
    db.execute("DELETE FROM login_attempts WHERE key = ?", (_keys(username)[0],))
    db.commit()


# ---- helpers ---------------------------------------------------------------------------------
def _password_ok(stored_hash, password):
    try:
        return _ph.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _matching_step(user, code):
    """Return the TOTP time-step that matches `code` (±1 step of drift) and was not used yet."""
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(user["totp_secret"])
    now_step = int(time.time() // MFA_STEP_SECONDS)
    for step in (now_step, now_step - 1, now_step + 1):
        if step > user["last_totp_step"] and totp.at(step * MFA_STEP_SECONDS) == code:
            return step
    return None


def _consume_step(user_id, step):
    """Atomically mark the step as used so a code can never be replayed."""
    db = get_db()
    cur = db.execute(
        "UPDATE users SET last_totp_step = ? WHERE id = ? AND last_totp_step < ?",
        (step, user_id, step),
    )
    db.commit()
    return cur.rowcount == 1


# ---- views -----------------------------------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("links.index"))
    if request.method == "POST":
        check_csrf()
        username = request.form.get("username", "").strip()[:64]
        password = request.form.get("password", "")[:256]
        if _throttled(username):
            flash("Too many failed attempts. Wait 15 minutes and try again.", "error")
            return render_template("login.html"), 429
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        ok = _password_ok(user["password_hash"] if user else _DUMMY_HASH, password)
        if not (ok and user):
            _record_failure(username)
            flash("Username or password is incorrect.", "error")
            return render_template("login.html"), 401
        session.clear()  # new session: no fixation
        session["mfa_uid"] = user["id"]
        session["mfa_until"] = time.time() + MFA_PENDING_SECONDS
        return redirect(url_for("auth.verify"))
    return render_template("login.html")


@bp.route("/login/verify", methods=["GET", "POST"])
def verify():
    uid = session.get("mfa_uid")
    if not uid or session.get("mfa_until", 0) < time.time():
        session.clear()
        return redirect(url_for("auth.login"))
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if user is None:
        session.clear()
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        check_csrf()
        if _throttled(user["username"]):
            flash("Too many failed attempts. Wait 15 minutes and try again.", "error")
            return render_template("mfa.html"), 429
        code = re.sub(r"\s+", "", request.form.get("code", ""))
        step = _matching_step(user, code)
        if step is None or not _consume_step(user["id"], step):
            _record_failure(user["username"])
            flash("That code is not valid. Enter the current code from your app.", "error")
            return render_template("mfa.html"), 401
        _clear_failures(user["username"])
        session.clear()
        session.permanent = True
        session["uid"] = user["id"]
        session["login_at"] = int(time.time())
        current_app.logger.info("auth.login user=%r ip=%s", user["username"], request.remote_addr)
        return redirect(url_for("links.index"))
    return render_template("mfa.html")


@bp.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("links.index"))
