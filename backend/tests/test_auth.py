"""Session auth (``lynceus.auth``, ``/auth/*`` routes and route guards).

Every case sets its own ``LYNCEUS_ADMIN_*`` environment (monkeypatch) and
builds a fresh app via ``create_app``; ``auth.reset_signer`` rotates the
in-memory server secret between cases so no token leaks across tests.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lynceus import auth
from lynceus.api import create_app
from lynceus.config import LYNCEUS_STORAGE_DIR_ENV

_USERNAME = "operator"
_PASSWORD = "correct horse battery staple"
_PASSWORD_SHA = hashlib.sha256(_PASSWORD.encode("utf-8")).hexdigest()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Auth-enabled app: plaintext password, empty storage dir."""
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, _USERNAME)
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, _PASSWORD)
    monkeypatch.delenv(auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV, raising=False)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    auth.reset_signer()
    yield TestClient(create_app())
    auth.reset_signer()


@pytest.fixture
def open_client(tmp_path, monkeypatch):
    """Auth-disabled app (demo mode): no admin env vars at all."""
    monkeypatch.delenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, raising=False)
    monkeypatch.delenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, raising=False)
    monkeypatch.delenv(auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV, raising=False)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    auth.reset_signer()
    yield TestClient(create_app())
    auth.reset_signer()


def test_disabled_mode_passes_everything_through(open_client):
    assert open_client.get("/health").status_code == 200
    session = open_client.get("/auth/session").json()
    assert session == {"authenticated": True, "user": ""}
    # A guarded API route answers normally without any cookie.
    assert open_client.get("/inspections").status_code == 200
    # Login is a no-op in demo mode and mints no cookie.
    response = open_client.post(
        "/auth/login", json={"username": "anyone", "password": "anything"}
    )
    assert response.status_code == 200
    assert auth.SESSION_COOKIE not in response.cookies


def test_login_success_sets_httponly_cookie(client):
    response = client.post(
        "/auth/login", json={"username": _USERNAME, "password": _PASSWORD}
    )
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "user": _USERNAME}
    cookie = response.headers["set-cookie"]
    assert f"{auth.SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    # Plain HTTP test client: the Secure attribute stays off.
    assert "secure" not in cookie.lower()


def test_login_accepts_sha256_env_over_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_USERNAME_ENV, _USERNAME)
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_ENV, "ignored plaintext")
    monkeypatch.setenv(auth.LYNCEUS_ADMIN_PASSWORD_SHA256_ENV, _PASSWORD_SHA)
    monkeypatch.setenv(LYNCEUS_STORAGE_DIR_ENV, str(tmp_path))
    auth.reset_signer()
    try:
        with TestClient(create_app()) as client:
            assert (
                client.post(
                    "/auth/login", json={"username": _USERNAME, "password": _PASSWORD}
                ).status_code
                == 200
            )
            # The plaintext value no longer matches: the digest won.
            assert (
                client.post(
                    "/auth/login",
                    json={"username": _USERNAME, "password": "ignored plaintext"},
                ).status_code
                == 401
            )
    finally:
        auth.reset_signer()


def test_wrong_password_is_401_with_generic_message(client):
    response = client.post(
        "/auth/login", json={"username": _USERNAME, "password": "wrong"}
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "invalid_credentials"
    # No username oracle: an unknown user gets the identical answer.
    other = client.post("/auth/login", json={"username": "nobody", "password": "x"})
    assert other.status_code == 401
    assert other.json() == response.json()


def test_wrong_password_is_delayed(client, monkeypatch):
    """The progressive delay fires: min(failures, 5) * 0.5 s per attempt."""
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(auth.asyncio, "sleep", _fake_sleep)
    # The per-username failure count is process-global; start clean so the
    # progression is measured from the first failure of this test.
    auth._failures.clear()
    body = {"username": _USERNAME, "password": "wrong"}
    client.post("/auth/login", json=body)
    client.post("/auth/login", json=body)
    client.post("/auth/login", json=body)
    assert slept == [0.5, 1.0, 1.5]


def test_session_endpoint_reflects_cookie(client):
    assert client.get("/auth/session").json() == {
        "authenticated": False,
        "user": None,
    }
    client.post("/auth/login", json={"username": _USERNAME, "password": _PASSWORD})
    assert client.get("/auth/session").json() == {
        "authenticated": True,
        "user": _USERNAME,
    }


def test_tampered_and_expired_tokens_are_rejected(client, monkeypatch):
    client.post("/auth/login", json={"username": _USERNAME, "password": _PASSWORD})
    token = client.cookies.get(auth.SESSION_COOKIE)
    issued, user, _sig = token.split(".")
    # Tampered signature: flip the last hex char.
    bad = f"{issued}.{user}." + ("0" if token[-1] != "0" else "1")
    client.cookies.set(auth.SESSION_COOKIE, bad)
    assert client.get("/auth/session").json()["authenticated"] is False
    # Expired: a signature for 13 h ago is well-formed but stale.
    settings = auth.get_auth_settings()
    stale = auth._get_signer(settings).sign(
        settings.username, int(issued) - (13 * 60 * 60)
    )
    client.cookies.set(auth.SESSION_COOKIE, stale)
    assert client.get("/auth/session").json()["authenticated"] is False


def test_logout_clears_the_cookie(client):
    client.post("/auth/login", json={"username": _USERNAME, "password": _PASSWORD})
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "user": None}
    assert client.get("/auth/session").json()["authenticated"] is False


def test_guarded_api_route_is_401_without_cookie(client):
    response = client.get("/inspections")
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "authentication_required"
    # Health and the auth routes themselves stay open.
    assert client.get("/health").status_code == 200
    assert client.get("/auth/session").status_code == 200


def test_guarded_api_route_answers_with_cookie(client):
    client.post("/auth/login", json={"username": _USERNAME, "password": _PASSWORD})
    assert client.get("/inspections").status_code == 200


def test_console_pages_redirect_to_login(client, monkeypatch, tmp_path):
    # An export to serve: only the redirect matters here, not the content.
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "app.html").write_text("<html>app</html>", encoding="utf-8")
    (web_dir / "shift.html").write_text("<html>shift</html>", encoding="utf-8")
    monkeypatch.setenv("LYNCEUS_WEB_DIR", str(web_dir))
    # The module-level _WEB_DIR was read at import; point the routes at it.
    import lynceus.api as api_mod

    monkeypatch.setattr(api_mod, "_WEB_DIR", web_dir)
    for path in ("/app", "/shift"):
        response = client.get(
            path, headers={"accept": "text/html"}, follow_redirects=False
        )
        assert response.status_code == 303, path
        assert response.headers["location"] == "/login.html"
    # Signed in: the page is served.
    client.post("/auth/login", json={"username": _USERNAME, "password": _PASSWORD})
    response = client.get("/app", headers={"accept": "text/html"})
    assert response.status_code == 200


def test_landing_page_stays_public(client, monkeypatch, tmp_path):
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("<html>landing</html>", encoding="utf-8")
    import lynceus.api as api_mod

    monkeypatch.setattr(api_mod, "_WEB_DIR", web_dir)
    with TestClient(create_app()) as fresh:
        response = fresh.get("/", headers={"accept": "text/html"})
    assert response.status_code == 200
