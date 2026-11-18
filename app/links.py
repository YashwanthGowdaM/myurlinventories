import sqlite3
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from .db import get_db
from .security import check_csrf, current_user, login_required

bp = Blueprint("links", __name__)

LIMITS = {"label": 80, "url": 2048, "description": 240}


def _url_error(url):
    if not url:
        return "Enter a URL."
    if len(url) > LIMITS["url"]:
        return f"Use at most {LIMITS['url']} characters."
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return "Remove spaces and control characters."
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return "This is not a valid URL."
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "Use a full address starting with http:// or https://."
    if parts.username or parts.password:
        return "Remove the username and password from the URL."
    return None


def validate(form):
    values = {k: " ".join(form.get(k, "").split()) if k != "url" else form.get(k, "").strip()
              for k in LIMITS}
    errors = {}
    if not values["label"]:
        errors["label"] = "Enter a label."
    elif len(values["label"]) > LIMITS["label"]:
        errors["label"] = f"Use at most {LIMITS['label']} characters."
    if err := _url_error(values["url"]):
        errors["url"] = err
    if len(values["description"]) > LIMITS["description"]:
        errors["description"] = f"Use at most {LIMITS['description']} characters."
    return values, errors


def _get_or_404(link_id):
    row = get_db().execute(
        "SELECT id, label, url, description FROM links WHERE id = ?", (link_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return dict(row)


@bp.get("/")
def index():
    rows = get_db().execute(
        "SELECT id, label, url, description FROM links ORDER BY label COLLATE NOCASE, id"
    ).fetchall()
    return render_template("index.html", links=[dict(r) for r in rows])


@bp.route("/links/new", methods=["GET", "POST"])
@login_required
def new():
    values, errors = {"label": "", "url": "", "description": ""}, {}
    if request.method == "POST":
        check_csrf()
        values, errors = validate(request.form)
        if not errors:
            who = current_user()["username"]
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO links(label, url, description, created_by, updated_by) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (values["label"], values["url"], values["description"], who, who),
                )
                db.commit()
            except sqlite3.IntegrityError:
                errors["url"] = "This URL is already in the list."
            else:
                current_app.logger.info("link.create id=%s by=%r", cur.lastrowid, who)
                flash("Link added.", "ok")
                return redirect(url_for("links.index"))
    status = 422 if errors else 200
    return render_template("form.html", values=values, errors=errors, mode="new"), status


@bp.route("/links/<int:link_id>/edit", methods=["GET", "POST"])
@login_required
def edit(link_id):
    link = _get_or_404(link_id)
    values, errors = link, {}
    if request.method == "POST":
        check_csrf()
        values, errors = validate(request.form)
        if not errors:
            who = current_user()["username"]
            db = get_db()
            try:
                db.execute(
                    "UPDATE links SET label = ?, url = ?, description = ?, updated_by = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (values["label"], values["url"], values["description"], who, link_id),
                )
                db.commit()
            except sqlite3.IntegrityError:
                errors["url"] = "This URL is already in the list."
            else:
                current_app.logger.info("link.update id=%s by=%r", link_id, who)
                flash("Changes saved.", "ok")
                return redirect(url_for("links.index"))
    status = 422 if errors else 200
    return render_template("form.html", values=values, errors=errors, mode="edit",
                           link_id=link_id), status


@bp.post("/links/<int:link_id>/delete")
@login_required
def delete(link_id):
    check_csrf()
    _get_or_404(link_id)
    db = get_db()
    db.execute("DELETE FROM links WHERE id = ?", (link_id,))
    db.commit()
    current_app.logger.info("link.delete id=%s by=%r", link_id, current_user()["username"])
    flash("Link deleted.", "ok")
    return redirect(url_for("links.index"))
