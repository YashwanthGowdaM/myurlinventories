import hmac
import secrets
import time
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for

from .db import get_db

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    expected = session.get("csrf", "")
    sent = request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(expected.encode(), sent.encode()):
        abort(400)


def current_user():
    """Return the signed-in user row, or None. Re-validated against the DB on every request."""
    if "user" in g:
        return g.user
    g.user = None
    uid = session.get("uid")
    if uid:
        age = time.time() - session.get("login_at", 0)
        if age > current_app.config["SESSION_MAX_AGE"]:
            session.clear()
        else:
            row = get_db().execute(
                "SELECT id, username FROM users WHERE id = ?", (uid,)
            ).fetchone()
            if row is None:
                session.clear()
            else:
                g.user = dict(row)
    return g.user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def init_app(app):
    @app.context_processor
    def inject():
        return {
            "csrf_token": csrf_token,
            "user": current_user(),
            "site_name": app.config["SITE_NAME"],
        }

    @app.after_request
    def set_headers(resp):
        h = resp.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.config["SESSION_COOKIE_SECURE"]:
            h["Strict-Transport-Security"] = "max-age=31536000"
        if request.endpoint != "static":
            h["Cache-Control"] = "no-store"
        return resp
