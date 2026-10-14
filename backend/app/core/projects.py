from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.data_import import create_dataset, import_uploaded_files, read_dataset_schema
from app.db import auth_store


def create_project(owner_id: str, name: str, files: list[tuple[str, str, bytes]]) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name is required")
    if len(name) > 80:
        raise HTTPException(status_code=422, detail="Project name must be 80 characters or fewer")

    imported_tables, source_files = import_uploaded_files(files)
    project_id = str(uuid.uuid4())
    data_path = str(_project_data_path(owner_id, project_id))
    try:
        schema = create_dataset(data_path, imported_tables)
    except Exception:
        Path(data_path).unlink(missing_ok=True)
        raise
    if not schema:
        Path(data_path).unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="No schema or data tables were found in the uploaded files")

    imported_at = datetime.now(timezone.utc).isoformat()
    try:
        with auth_store.connection() as db:
            project_columns = {row[1] for row in db.execute("PRAGMA table_info(projects)").fetchall()}
            if "encrypted_database_url" in project_columns:
                db.execute(
                    """INSERT INTO projects
                       (id, owner_id, name, encrypted_database_url, schema_snapshot, data_path, source_files, imported_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (project_id, owner_id, name, b"", json.dumps(schema), data_path, json.dumps(source_files), imported_at, imported_at),
                )
            else:
                db.execute(
                    """INSERT INTO projects
                       (id, owner_id, name, schema_snapshot, data_path, source_files, imported_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (project_id, owner_id, name, json.dumps(schema), data_path, json.dumps(source_files), imported_at, imported_at),
                )
    except sqlite3.IntegrityError as exc:
        Path(data_path).unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="A project with this name already exists") from exc
    return get_owned_project(owner_id, project_id)


def _project_data_path(owner_id: str, project_id: str) -> Path:
    root = Path(get_settings().app_database_path).resolve().parent / "projects" / owner_id
    return root / f"{project_id}.duckdb"


def get_owned_project(owner_id: str, project_id: str) -> dict[str, Any]:
    with auth_store.connection() as db:
        row = db.execute(
            "SELECT * FROM projects WHERE id = ? AND owner_id = ?",
            (project_id, owner_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = dict(row)
    project["schema_snapshot"] = json.loads(project["schema_snapshot"])
    project["source_files"] = json.loads(project["source_files"] or "[]")
    project.pop("encrypted_database_url", None)
    if not project["data_path"]:
        raise HTTPException(status_code=409, detail="This legacy project has no imported dataset; create a new file-based project")
    return project


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project["id"],
        "name": project["name"],
        "schema": project["schema_snapshot"],
        "imported_at": project["imported_at"],
        "allow_mutations": bool(project["allow_mutations"]),
        "source_files": project["source_files"],
        "row_count": sum(table.get("row_count", 0) for table in project["schema_snapshot"]),
        "created_at": project["created_at"],
    }


def list_projects(owner_id: str) -> list[dict[str, Any]]:
    with auth_store.connection() as db:
        rows = db.execute(
            "SELECT * FROM projects WHERE owner_id = ? AND data_path <> '' ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
    return [public_project(get_owned_project(owner_id, row["id"])) for row in rows]


def refresh_project_schema(owner_id: str, project_id: str) -> dict[str, Any]:
    project = get_owned_project(owner_id, project_id)
    schema = read_dataset_schema(project["data_path"])
    if not schema:
        raise HTTPException(status_code=422, detail="The imported dataset contains no tables")
    previous_tables = {table["name"]: table for table in project["schema_snapshot"]}
    for table in schema:
        previous = previous_tables.get(table["name"], {})
        previous_columns = {column["name"]: column for column in previous.get("columns", [])}
        for column in table["columns"]:
            column["is_primary_key"] = previous_columns.get(column["name"], {}).get("is_primary_key", False)
        table["primary_keys"] = [column["name"] for column in table["columns"] if column["is_primary_key"]]
        table["foreign_keys"] = previous.get("foreign_keys", [])
    imported_at = datetime.now(timezone.utc).isoformat()
    with auth_store.connection() as db:
        db.execute(
            "UPDATE projects SET schema_snapshot = ?, imported_at = ? WHERE id = ? AND owner_id = ?",
            (json.dumps(schema), imported_at, project_id, owner_id),
        )
    return public_project(get_owned_project(owner_id, project_id))


def update_project(owner_id: str, project_id: str, *, name: str | None = None, allow_mutations: bool | None = None) -> dict[str, Any]:
    get_owned_project(owner_id, project_id)
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
    return public_project(get_owned_project(owner_id, project_id))


def delete_project(owner_id: str, project_id: str) -> None:
    project = get_owned_project(owner_id, project_id)
    with auth_store.connection() as db:
        db.execute("DELETE FROM projects WHERE id = ? AND owner_id = ?", (project_id, owner_id))
    Path(project["data_path"]).unlink(missing_ok=True)
