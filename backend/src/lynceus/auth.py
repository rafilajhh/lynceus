"""Session authentication for the Lynceus console (optional, env-driven).

When ``LYNCEUS_ADMIN_USERNAME`` and a password (plaintext
``LYNCEUS_ADMIN_PASSWORD`` or its hex SHA-256 in
``LYNCEUS_ADMIN_PASSWORD_SHA256``) are both set, the console pages and the
API require a session cookie; when either is unset the deployment runs as
an open demo and every guard passes through.  Tokens are HMAC-SHA256
signatures built with the stdlib only (``hmac`` / ``hashlib`` /
``secrets``) — no third-party signing dependency.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

#: Environment knobs (see config.py for the pattern; auth config is read
#: here so the module stays importable without the rest of the settings).
LYNCEUS_ADMIN_USERNAME_ENV = "LYNCEUS_ADMIN_USERNAME"
LYNCEUS_ADMIN_PASSWORD_ENV = "LYNCEUS_ADMIN_PASSWORD"
LYNCEUS_ADMIN_PASSWORD_SHA256_ENV = "LYNCEUS_ADMIN_PASSWORD_SHA256"

#: Session cookie name and lifetime (12 h shift).
SESSION_COOKIE = "lynceus_session"
SESSION_MAX_AGE_S = 12 * 60 * 60

#: Failure throttle: after ``n`` failed logins for a username, the answer
#: waits ``min(n, 5) * 0.5`` seconds — cheap against online guessing,
#: harmless to an operator who mistyped once.
_FAILURE_DELAY_STEP_S = 0.5
_FAILURE_DELAY_MAX_N = 5

#: Signed token shape: "<issued_unix>.<username>.<hmac-hex>".
_TOKEN_VERSION = "v1"


@dataclass(frozen=True)
class AuthSettings:
    """Auth snapshot from the environment; ``enabled=False`` is demo mode."""

    enabled: bool
    username: str
    password_sha256: str  # hex digest of the configured password; "" when off


def get_auth_settings() -> AuthSettings:
    """Read auth config from the environment (per call, like get_settings).

    Auth is enabled only when a username AND a password are both configured;
    ``LYNCEUS_ADMIN_PASSWORD_SHA256`` (hex digest) takes precedence over the
    plaintext ``LYNCEUS_ADMIN_PASSWORD`` so deployments never need to store
    the raw password.  A malformed digest falls back to the plaintext value.
    """
    username = os.environ.get(LYNCEUS_ADMIN_USERNAME_ENV, "").strip()
    digest = os.environ.get(LYNCEUS_ADMIN_PASSWORD_SHA256_ENV, "").strip().lower()
    if not (len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
        digest = ""
    plaintext = os.environ.get(LYNCEUS_ADMIN_PASSWORD_ENV, "")
    if not digest and plaintext:
        digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    enabled = bool(username and digest)
    return AuthSettings(enabled=enabled, username=username, password_sha256=digest)


def _password_digest(password: str) -> str:
    """Hex SHA-256 of a candidate password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


class _Signer:
    """HMAC key derived at startup: password hash ⊕ in-memory random secret.

    The random half lives only in process memory, so a token from one run
    can never be validated by another — restart logs everyone out, and the
    password hash alone (e.g. from an env file leak) cannot mint tokens.
    """

    def __init__(self, settings: AuthSettings) -> None:
        self._key = hashlib.sha256(
            settings.password_sha256.encode("ascii") + secrets.token_bytes(32)
        ).digest()

    def sign(self, username: str, issued: int) -> str:
        payload = f"{_TOKEN_VERSION}.{issued}.{username}".encode("utf-8")
        return f"{issued}.{username}." + hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, token: str, username: str) -> bool:
        """True when ``token`` is a fresh signature for ``username``."""
        try:
            issued_s, token_user, sig = token.split(".")
            issued = int(issued_s)
        except (ValueError, AttributeError):
            return False
        if token_user != username or time.time() - issued > SESSION_MAX_AGE_S:
            return False
        expected = hmac.new(
            self._key,
            f"{_TOKEN_VERSION}.{issued}.{username}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, sig)


#: Per-process signer, built lazily on first use so tests can flip env vars
#: between cases; ``_signer_lock`` keeps concurrent first requests safe.
_signer: _Signer | None = None
_signer_lock = threading.Lock()


def _get_signer(settings: AuthSettings) -> _Signer:
    global _signer
    with _signer_lock:
        if _signer is None:
            _signer = _Signer(settings)
        return _signer


def reset_signer() -> None:
    """Drop the cached signer (tests rotate the server secret this way)."""
    global _signer
    with _signer_lock:
        _signer = None


#: Failed-login counts per username, for the progressive delay.  In-memory
#: only: a restart resets the throttle, which is fine for a demo deployment.
_failures: dict[str, int] = {}
_failures_lock = threading.Lock()


class LoginRequest(BaseModel):
    """Credentials submitted by the login page."""

    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


def current_user(request: Request) -> str | None:
    """The session's username, or ``None`` when there is no valid session.

    Auth-disabled deployments report the configured username (empty string)
    so callers can treat "auth off" as "always authenticated"; ``require_auth``
    below is the no-op guard for that mode.
    """
    settings = get_auth_settings()
    if not settings.enabled:
        return settings.username
    token = request.cookies.get(SESSION_COOKIE, "")
    if token and _get_signer(settings).verify(token, settings.username):
        return settings.username
    return None


def require_auth(request: Request) -> str | None:
    """FastAPI dependency: 401 JSON unless a valid session (or auth is off)."""
    user = current_user(request)
    if get_auth_settings().enabled and user is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "authentication_required", "message": "Sign in first."},
        )
    return user


def register_auth_routes(app: FastAPI) -> None:
    """Mount ``/auth/login``, ``/auth/logout`` and ``/auth/session``."""

    @app.post("/auth/login")
    async def login(body: LoginRequest, request: Request, response: Response) -> dict:
        """Verify credentials; on success set the HttpOnly session cookie.

        The failure path is deliberately uniform: same 401, same generic
        message, and a progressive per-username delay — no oracle for "user
        exists" or "password almost right".
        """
        settings = get_auth_settings()
        if not settings.enabled:
            # Demo mode: nothing to check, and no cookie to mint.
            return {"authenticated": True, "user": settings.username}
        ok = hmac.compare_digest(body.username, settings.username) and hmac.compare_digest(
            _password_digest(body.password), settings.password_sha256
        )
        if not ok:
            with _failures_lock:
                count = _failures.get(body.username, 0) + 1
                _failures[body.username] = count
            delay = min(count, _FAILURE_DELAY_MAX_N) * _FAILURE_DELAY_STEP_S
            # Async sleep so a slow-bombed login never blocks the loop.
            await asyncio.sleep(delay)
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_credentials", "message": "Invalid username or password."},
            )
        with _failures_lock:
            _failures.pop(body.username, None)
        token = _get_signer(settings).sign(settings.username, int(time.time()))
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_MAX_AGE_S,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return {"authenticated": True, "user": settings.username}

    @app.post("/auth/logout")
    def logout(response: Response) -> dict:
        """Clear the session cookie; always 200 (idempotent sign-out)."""
        response.delete_cookie(SESSION_COOKIE, samesite="lax")
        return {"authenticated": False, "user": None}

    @app.get("/auth/session")
    def session(request: Request) -> dict:
        """Who is signed in, for the frontend's boot-time check."""
        user = current_user(request)
        return {"authenticated": user is not None, "user": user}
