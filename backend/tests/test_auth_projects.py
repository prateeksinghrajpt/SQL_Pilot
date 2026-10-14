import base64
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.api.routes.auth import CSRF_COOKIE
from app.api.routes.projects import router as projects_router
from app.core import projects as project_service
from app.core import security
from app.db import auth_store
from app.main import app

SCHEMA = [
    {
        "name": "customers",
        "columns": [
            {"name": "id", "type": "integer", "nullable": False, "is_primary_key": True},
            {"name": "email", "type": "text", "nullable": False, "is_primary_key": False},
        ],
        "primary_keys": ["id"],
        "foreign_keys": [],
    }
]


@pytest.fixture
def client_and_key(monkeypatch, tmp_path):
    encryption_key = base64.urlsafe_b64encode(b"x" * 32).decode()
    settings = SimpleNamespace(
        app_database_path=str(tmp_path / "control.sqlite3"),
        credential_encryption_key=encryption_key,
        cookie_secure=False,
        allow_private_database_hosts=True,
    )
    monkeypatch.setattr(auth_store, "get_settings", lambda: settings)
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    return TestClient(app), settings


def test_registration_login_and_csrf_protected_logout(client_and_key):
    client, _settings = client_and_key
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "First.User@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 201
    assert "correct horse" not in response.text
    assert client.cookies.get("sql_copilot_session")
    assert client.cookies.get(CSRF_COOKIE)
    assert client.get("/api/v1/auth/me").json()["user"]["email"] == "first.user@example.com"

    csrf_token = client.cookies.get(CSRF_COOKIE)
    without_csrf = client.post("/api/v1/auth/logout")
    assert without_csrf.status_code == 403

    logged_out = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert logged_out.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "FIRST.USER@example.com", "password": "correct horse battery staple"},
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_sql_execution_requires_csrf_token(client_and_key):
    client, _settings = client_and_key
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "csrf@example.com", "password": "valid long password"},
    )
    assert registered.status_code == 201
    payload = {"project_id": "missing-project", "sql": "SELECT id FROM customers;"}

    without_csrf = client.post("/api/v1/sql/run", json=payload)
    assert without_csrf.status_code == 403

    with_csrf = client.post(
        "/api/v1/sql/run",
        json=payload,
        headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE)},
    )
    assert with_csrf.status_code == 404


def test_project_credentials_are_encrypted_and_not_returned(client_and_key, monkeypatch):
    client, settings = client_and_key
    assert client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "a secure project password"},
    ).status_code == 201
    csrf_token = client.cookies.get(CSRF_COOKIE)
    monkeypatch.setattr(project_service, "import_schema", lambda database_url: SCHEMA)

    created = client.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "name": "Project 1",
            "database_url": "postgresql://project_user:secret-password@db.example.com/customer_data",
        },
    )

    assert created.status_code == 201
    project = created.json()["project"]
    assert project["name"] == "Project 1"
    assert project["schema"][0]["name"] == "customers"
    assert "database_url" not in project
    assert "secret-password" not in created.text

    with sqlite3.connect(settings.app_database_path) as db:
        encrypted = db.execute("SELECT encrypted_database_url FROM projects").fetchone()[0]
    assert b"secret-password" not in encrypted

    listed = client.get("/api/v1/projects")
    assert listed.status_code == 200
    assert listed.json()["projects"][0]["id"] == project["id"]
    assert "database_url" not in listed.text


def test_project_isolation_refresh_and_policy(client_and_key, monkeypatch):
    client_a, settings = client_and_key
    registered_a = client_a.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": "long enough password a"},
    )
    assert registered_a.status_code == 201
    csrf_a = client_a.cookies.get(CSRF_COOKIE)
    monkeypatch.setattr(project_service, "import_schema", lambda database_url: SCHEMA)
    created = client_a.post(
        "/api/v1/projects",
        headers={"X-CSRF-Token": csrf_a},
        json={"name": "Analytics", "database_url": "postgresql://a:password@db.example.com/a"},
    )
    project_id = created.json()["project"]["id"]

    client_b = TestClient(app)
    registered_b = client_b.post(
        "/api/v1/auth/register",
        json={"email": "b@example.com", "password": "long enough password b"},
    )
    assert registered_b.status_code == 201
    assert client_b.get(f"/api/v1/projects/{project_id}").status_code == 404
    assert client_b.post(
        f"/api/v1/projects/{project_id}/refresh-schema",
        headers={"X-CSRF-Token": client_b.cookies.get(CSRF_COOKIE)},
    ).status_code == 404

    refreshed_schema = [{
        "name": "orders",
        "columns": [{"name": "id", "type": "integer", "nullable": False, "is_primary_key": True}],
        "primary_keys": ["id"],
        "foreign_keys": [],
    }]
    monkeypatch.setattr(project_service, "import_schema", lambda database_url: refreshed_schema)
    refreshed = client_a.post(
        f"/api/v1/projects/{project_id}/refresh-schema",
        headers={"X-CSRF-Token": csrf_a},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["project"]["schema"][0]["name"] == "orders"

    changed = client_a.patch(
        f"/api/v1/projects/{project_id}",
        headers={"X-CSRF-Token": csrf_a},
        json={"allow_mutations": True},
    )
    assert changed.status_code == 200
    assert changed.json()["project"]["allow_mutations"] is True

    assert client_a.delete(
        f"/api/v1/projects/{project_id}",
        headers={"X-CSRF-Token": csrf_a},
    ).status_code == 204
    assert client_a.get(f"/api/v1/projects/{project_id}").status_code == 404


def test_database_url_rejects_private_dns_results(monkeypatch):
    monkeypatch.setattr(
        project_service,
        "get_settings",
        lambda: SimpleNamespace(allow_private_database_hosts=False),
    )
    monkeypatch.setattr(
        project_service.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 5432))],
    )

    with pytest.raises(HTTPException) as error:
        project_service.validate_database_url("postgresql://user:password@internal.example/data")

    assert error.value.status_code == 422
    assert "Private or local" in error.value.detail


def test_database_url_rejects_non_postgres_scheme():
    with pytest.raises(HTTPException) as error:
        project_service.validate_database_url("mysql://user:password@db.example.com/data")

    assert error.value.status_code == 422
