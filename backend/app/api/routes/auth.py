from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session,
    get_current_user,
    hash_password,
    require_csrf,
    set_session_cookies,
    token_hash,
    verify_password,
)
from app.db import auth_store

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return normalized


def _issue_session(response: Response, user_id: str, email: str) -> dict[str, Any]:
    session_token, csrf_token = create_session(user_id)
    set_session_cookies(response, session_token, csrf_token)
    return {"user": {"id": user_id, "email": email}}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: Credentials, response: Response) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    user_id = str(uuid.uuid4())
    try:
        with auth_store.connection() as db:
            db.execute(
                "INSERT INTO users(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, email, hash_password(payload.password), auth_store.utc_now()),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
    return _issue_session(response, user_id, email)


@router.post("/login")
def login(payload: Credentials, response: Response) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    with auth_store.connection() as db:
        user = db.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return _issue_session(response, user["id"], user["email"])


@router.get("/me")
def current_user(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": user}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: dict[str, Any] = Depends(get_current_user)) -> Response:
    require_csrf(request, user)
    session_token = request.cookies.get(SESSION_COOKIE, "")
    with auth_store.connection() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(session_token),))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response