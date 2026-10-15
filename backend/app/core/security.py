from __future__ import annotations

import hmac
import hashlib
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.db import auth_store

SESSION_COOKIE = "sql_copilot_session"
CSRF_COOKIE = "sql_copilot_csrf"
SESSION_TTL_SECONDS = 60 * 60 * 12
_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: str) -> tuple[str, str]:
    import time

    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    with auth_store.connection() as db:
        db.execute(
            "INSERT INTO sessions(token_hash, csrf_hash, user_id, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash(session_token), token_hash(csrf_token), user_id, expires_at),
        )
    return session_token, csrf_token


def get_current_user(request: Request) -> dict[str, Any]:
    import time

    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    with auth_store.connection() as db:
        row = db.execute(
            """SELECT users.id, users.email, users.approval_status, sessions.csrf_hash, sessions.expires_at
               FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ?""",
            (token_hash(session_token),),
        ).fetchone()
    if row is None or row["expires_at"] <= int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    if row["approval_status"] not in ("trial", "approved"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your access request is awaiting administrator approval")
    request.state.session_csrf_hash = row["csrf_hash"]
    return {"id": row["id"], "email": row["email"]}


def require_csrf(request: Request, user: dict[str, Any]) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    stored_hash = getattr(request.state, "session_csrf_hash", "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    if not hmac.compare_digest(token_hash(header_token), stored_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


def get_current_user_with_csrf(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    require_csrf(request, user)
    return user


def set_session_cookies(response: Any, session_token: str, csrf_token: str) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )
