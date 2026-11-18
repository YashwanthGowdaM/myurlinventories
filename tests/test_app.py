import re
import time

import pyotp
import pytest
from argon2 import PasswordHasher

from app import create_app
from app.db import get_db

PASSWORD = "correct horse battery staple"
TOTP_SECRET = pyotp.random_base32()


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "k" * 40,
        "SESSION_COOKIE_SECURE": False,
    })
    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO users(username, password_hash, totp_secret) VALUES (?, ?, ?)",
            ("admin", PasswordHasher().hash(PASSWORD), TOTP_SECRET),
        )
        db.commit()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def token(client, path):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def current_code(offset=0):
    return pyotp.TOTP(TOTP_SECRET).at((int(time.time() // 30) + offset) * 30)


def sign_in(client, code=None):
    r = client.post("/login", data={"username": "admin", "password": PASSWORD,
                                    "csrf_token": token(client, "/login")})
    assert r.status_code == 302
    return client.post("/login/verify", data={"code": code or current_code(),
                                              "csrf_token": token(client, "/login/verify")})


def add_link(client, url="https://example.com", label="Example", **extra):
    return client.post("/links/new", data={"label": label, "url": url, "description": "d",
                                           "csrf_token": token(client, "/links/new"), **extra})


def test_public_page_is_read_only(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Add link" not in r.get_data(as_text=True)


def test_write_requires_login(client):
    assert client.get("/links/new").status_code == 302
    assert client.post("/links/new", data={}).status_code == 302


def test_full_flow(client):
    assert sign_in(client).status_code == 302
    assert add_link(client).status_code == 302
    html = client.get("/").get_data(as_text=True)
    assert "Example" in html and "Edit" in html


def test_wrong_password_is_generic(client):
    r = client.post("/login", data={"username": "admin", "password": "nope",
                                    "csrf_token": token(client, "/login")})
    assert r.status_code == 401
    r2 = client.post("/login", data={"username": "ghost", "password": "nope",
                                     "csrf_token": token(client, "/login")})
    assert r2.status_code == 401


def test_totp_replay_rejected(app):
    code = current_code()
    first, second = app.test_client(), app.test_client()
    assert sign_in(first, code).status_code == 302
    assert sign_in(second, code).status_code == 401


def test_password_alone_is_not_a_session(client):
    client.post("/login", data={"username": "admin", "password": PASSWORD,
                                "csrf_token": token(client, "/login")})
    assert client.get("/links/new").status_code == 302


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,x", "ftp://x.org",
                                 "https://user:pw@example.com", "https://exa mple.com", "//x.org"])
def test_bad_urls_rejected(client, bad):
    sign_in(client)
    assert add_link(client, url=bad).status_code == 422


def test_duplicate_url_rejected(client):
    sign_in(client)
    add_link(client)
    assert add_link(client).status_code == 422


def test_csrf_enforced(client):
    sign_in(client)
    r = client.post("/links/new", data={"label": "x", "url": "https://x.org"})
    assert r.status_code == 400


def test_security_headers(client):
    h = client.get("/").headers
    assert "script-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Frame-Options"] == "DENY"
    assert h["X-Content-Type-Options"] == "nosniff"


def test_xss_is_escaped(client):
    sign_in(client)
    add_link(client, label="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in client.get("/").get_data(as_text=True)
