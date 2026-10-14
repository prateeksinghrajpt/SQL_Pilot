from __future__ import annotations

import ipaddress
import json
import socket
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import psycopg
from fastapi import HTTPException

from app.core.security import decrypt_database_url, encrypt_database_url
from app.core.config import get_settings
from app.db import auth_store


def validate_database_url(database_url: str) -> bool:
    try:
        parsed = urlsplit(database_url)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("Only PostgreSQL URLs with a host and database name are supported")
        if not parsed.username:
            raise ValueError("A database username is required")
        port = parsed.port or 5432
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="The database host could not be resolved") from exc

    private_target = any(not address.is_global for address in addresses)
    if private_target and not get_settings().allow_private_database_hosts:
        raise HTTPException(
            status_code=422,
            detail="Private or local database hosts are disabled. Enable them only for trusted development networks.",
        )
    return private_target


def connect_project_db(database_url: str) -> psycopg.Connection[Any]:
    private_target = validate_database_url(database_url)
    return psycopg.connect(
        database_url,
        connect_timeout=5,
        sslmode="prefer" if private_target else "require",
    )


def import_schema(database_url: str) -> list[dict[str, Any]]:
    try:
        with connect_project_db(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT table_name
                       FROM information_schema.tables
                       WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                       ORDER BY table_name"""
                )
                table_names = [row[0] for row in cursor.fetchall()]
                tables: list[dict[str, Any]] = []
                for table_name in table_names:
                    cursor.execute(
                        """SELECT column_name, data_type, is_nullable
                           FROM information_schema.columns
                           WHERE table_schema = 'public' AND table_name = %s
                           ORDER BY ordinal_position""",
                        (table_name,),
                    )
                    columns = cursor.fetchall()
                    cursor.execute(
                        """SELECT kcu.column_name
                           FROM information_schema.table_constraints tc
                           JOIN information_schema.key_column_usage kcu
                             ON tc.constraint_name = kcu.constraint_name
                           WHERE tc.table_schema = 'public' AND tc.table_name = %s
                             AND tc.constraint_type = 'PRIMARY KEY'
                           ORDER BY kcu.ordinal_position""",
                        (table_name,),
                    )
                    primary_keys = [row[0] for row in cursor.fetchall()]
                    cursor.execute(
                        """SELECT kcu.column_name, ccu.table_name, ccu.column_name
                           FROM information_schema.table_constraints tc
                           JOIN information_schema.key_column_usage kcu
                             ON tc.constraint_name = kcu.constraint_name
                           JOIN information_schema.constraint_column_usage ccu
                             ON ccu.constraint_name = tc.constraint_name
                           WHERE tc.table_schema = 'public' AND tc.table_name = %s
                             AND tc.constraint_type = 'FOREIGN KEY'""",
                        (table_name,),
                    )
                    foreign_keys = [
                        {"column": row[0], "references_table": row[1], "references_column": row[2]}
                        for row in cursor.fetchall()
                    ]
                    tables.append(
                        {
                            "name": table_name,
                            "columns": [
                                {
                                    "name": column_name,
                                    "type": data_type,
                                    "nullable": is_nullable == "YES",
                                    "is_primary_key": column_name in primary_keys,
                                }
                                for column_name, data_type, is_nullable in columns
                            ],
                            "primary_keys": primary_keys,
                            "foreign_keys": foreign_keys,
                        }
                    )
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise HTTPException(status_code=422, detail="Could not connect to the PostgreSQL database") from exc
    return tables


def create_project(owner_id: str, name: str, database_url: str) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name is required")
    if len(name) > 80:
        raise HTTPException(status_code=422, detail="Project name must be 80 characters or fewer")

    encrypted_url = encrypt_database_url(database_url)
    schema = import_schema(database_url)
    if not schema:
        raise HTTPException(status_code=422, detail="No public tables were found in this database")

    project_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc).isoformat()
    try:
        with auth_store.connection() as db:
            db.execute(
                """INSERT INTO projects
                   (id, owner_id, name, encrypted_database_url, schema_snapshot, imported_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, owner_id, name, encrypted_url, json.dumps(schema), imported_at, imported_at),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A project with this name already exists") from exc
    return get_owned_project(owner_id, project_id, include_database_url=False)


def get_owned_project(owner_id: str, project_id: str, *, include_database_url: bool = True) -> dict[str, Any]:
    with auth_store.connection() as db:
        row = db.execute(
            "SELECT * FROM projects WHERE id = ? AND owner_id = ?",
            (project_id, owner_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = dict(row)
    project["schema_snapshot"] = json.loads(project["schema_snapshot"])
    encrypted_url = project.pop("encrypted_database_url")
    if include_database_url:
        project["database_url"] = decrypt_database_url(encrypted_url)
    return project


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project["id"],
        "name": project["name"],
        "schema": project["schema_snapshot"],
        "imported_at": project["imported_at"],
        "allow_mutations": bool(project["allow_mutations"]),
        "created_at": project["created_at"],
    }


def list_projects(owner_id: str) -> list[dict[str, Any]]:
    with auth_store.connection() as db:
        rows = db.execute(
            "SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
    return [public_project(get_owned_project(owner_id, row["id"], include_database_url=False)) for row in rows]


def refresh_project_schema(owner_id: str, project_id: str) -> dict[str, Any]:
    project = get_owned_project(owner_id, project_id)
    schema = import_schema(project["database_url"])
    if not schema:
        raise HTTPException(status_code=422, detail="No public tables were found in this database")
    imported_at = datetime.now(timezone.utc).isoformat()
    with auth_store.connection() as db:
        db.execute(
            "UPDATE projects SET schema_snapshot = ?, imported_at = ? WHERE id = ? AND owner_id = ?",
            (json.dumps(schema), imported_at, project_id, owner_id),
        )
    return public_project(get_owned_project(owner_id, project_id, include_database_url=False))


def update_project(owner_id: str, project_id: str, *, name: str | None = None, allow_mutations: bool | None = None) -> dict[str, Any]:
    get_owned_project(owner_id, project_id, include_database_url=False)
    updates: list[str] = []
    values: list[Any] = []
    if name is not None:
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 80:
            raise HTTPException(status_code=422, detail="Project name must contain 1 to 80 characters")
        updates.append("name = ?")
        values.append(normalized_name)
    if allow_mutations is not None:
        updates.append("allow_mutations = ?")
        values.append(int(allow_mutations))
    if updates:
        values.extend([project_id, owner_id])
        try:
            with auth_store.connection() as db:
                db.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ? AND owner_id = ?", values)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="A project with this name already exists") from exc
    return public_project(get_owned_project(owner_id, project_id, include_database_url=False))


def delete_project(owner_id: str, project_id: str) -> None:
    get_owned_project(owner_id, project_id, include_database_url=False)
    with auth_store.connection() as db:
        db.execute("DELETE FROM projects WHERE id = ? AND owner_id = ?", (project_id, owner_id))
