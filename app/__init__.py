import logging
import os
from datetime import timedelta

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import auth, db, links, security


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", ""),
        DATABASE=os.path.join(os.environ.get("DATA_DIR", "/data"), "urls.db"),
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_MAX_AGE=8 * 3600,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=16 * 1024,
        JSON_SORT_KEYS=False,
        SITE_NAME="Link Registry",
    )
    if test_config:
        app.config.update(test_config)

    if len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("SECRET_KEY must be set and at least 32 characters long")

    # The __Host- prefix pins the cookie to this exact host over HTTPS only.
    app.config["SESSION_COOKIE_NAME"] = (
        "__Host-session" if app.config["SESSION_COOKIE_SECURE"] else "session"
    )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app.logger.setLevel(logging.INFO)

    # Exactly one trusted proxy (Caddy) in front of the app.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    security.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(links.bp)

    @app.get("/healthz")
    def healthz():
        db.get_db().execute("SELECT 1").fetchone()
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    messages = {
        400: "The request could not be verified. Reload the page and try again.",
        404: "That page does not exist.",
        405: "That action is not allowed here.",
        413: "The request was too large.",
        500: "Something went wrong on the server.",
    }

    def handler(err):
        code = getattr(err, "code", 500)
        return render_template("error.html", code=code, message=messages.get(code, "Error.")), code

    for code in messages:
        app.register_error_handler(code, handler)

    return app
