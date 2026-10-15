from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.core.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'trial',
    free_queries_used INTEGER NOT NULL DEFAULT 0,
    access_requested_at TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    csrf_hash TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    schema_snapshot TEXT NOT NULL,
    data_path TEXT NOT NULL DEFAULT '',
    source_files TEXT NOT NULL DEFAULT '[]',
    imported_at TEXT NOT NULL,
    allow_mutations INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(owner_id, name)
);
CREATE INDEX IF NOT EXISTS projects_owner_id_idx ON projects(owner_id);
INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
"""


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = Path(get_settings().app_database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "approval_status" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'trial'")
    if "free_queries_used" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN free_queries_used INTEGER NOT NULL DEFAULT 0")
    if "access_requested_at" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN access_requested_at TEXT")
    if "is_admin" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    settings = get_settings()
    admin_email = getattr(settings, "admin_email", None)
    if admin_email:
        db.execute(
            """UPDATE users
               SET is_admin = 1, approval_status = 'approved'
               WHERE email = ? COLLATE NOCASE""",
            (admin_email.strip().lower(),),
        )
    project_columns = {row[1] for row in db.execute("PRAGMA table_info(projects)").fetchall()}
    if "data_path" not in project_columns:
        db.execute("ALTER TABLE projects ADD COLUMN data_path TEXT NOT NULL DEFAULT ''")
    if "source_files" not in project_columns:
        db.execute("ALTER TABLE projects ADD COLUMN source_files TEXT NOT NULL DEFAULT '[]'")
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (2, ?)",
        (utc_now(),),
    )
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_user_access(user_id: str) -> dict[str, Any] | None:
    with connection() as db:
        row = db.execute(
            """SELECT id, email, approval_status, free_queries_used, access_requested_at, is_admin
               FROM users
               WHERE id = ?""",
            (user_id,),
        ).fetchone()
    return row_to_dict(row)


def consume_free_generation(user_id: str) -> dict[str, Any]:
    with connection() as db:
        row = db.execute(
            """SELECT approval_status, free_queries_used
               FROM users
               WHERE id = ?""",
            (user_id,),
        ).fetchone()
        if row is None:
            return {"allowed": False, "reason": "missing"}
        if row["approval_status"] == "approved":
            return {"allowed": True, "remaining_free_queries": None}
        if row["approval_status"] != "trial":
            return {"allowed": False, "reason": row["approval_status"]}
        if int(row["free_queries_used"]) >= 1:
            return {"allowed": False, "reason": "free_query_used"}
        db.execute(
            "UPDATE users SET free_queries_used = free_queries_used + 1 WHERE id = ?",
            (user_id,),
        )
    return {"allowed": True, "remaining_free_queries": 0}


def can_generate_sql(user_id: str) -> dict[str, Any]:
    access = get_user_access(user_id)
    if access is None:
        return {"allowed": False, "reason": "missing"}
    if access["approval_status"] == "approved":
        return {"allowed": True, "remaining_free_queries": None}
    if access["approval_status"] != "trial":
        return {"allowed": False, "reason": access["approval_status"]}
    if int(access["free_queries_used"]) >= 1:
        return {"allowed": False, "reason": "free_query_used"}
    return {"allowed": True, "remaining_free_queries": 1}


def mark_access_requested(user_id: str) -> dict[str, Any] | None:
    requested_at = utc_now()
    with connection() as db:
        row = db.execute(
            "SELECT id, email, access_requested_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        if row["access_requested_at"]:
            existing = row_to_dict(row)
            existing["notification_needed"] = False
            return existing
        db.execute(
            "UPDATE users SET access_requested_at = ? WHERE id = ?",
            (requested_at, user_id),
        )
        return {
            "id": row["id"],
            "email": row["email"],
            "access_requested_at": requested_at,
            "notification_needed": True,
        }


def list_access_requests() -> list[dict[str, Any]]:
    with connection() as db:
        rows = db.execute(
            """SELECT id, email, approval_status, free_queries_used, access_requested_at, created_at
               FROM users
               WHERE access_requested_at IS NOT NULL
                  OR approval_status IN ('pending', 'rejected')
               ORDER BY access_requested_at DESC, created_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def set_user_approval(user_id: str, approved: bool) -> dict[str, Any] | None:
    status = "approved" if approved else "rejected"
    with connection() as db:
        db.execute(
            """UPDATE users
               SET approval_status = ?
               WHERE id = ? AND is_admin = 0""",
            (status, user_id),
        )
        row = db.execute(
            """SELECT id, email, approval_status, free_queries_used, access_requested_at, created_at
               FROM users
               WHERE id = ?""",
            (user_id,),
        ).fetchone()
    return row_to_dict(row)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
