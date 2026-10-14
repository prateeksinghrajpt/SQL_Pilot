from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routes import sql as sql_routes
from app.core.security import get_current_user_with_csrf
from app.main import app

client = TestClient(app)
USER = {"id": "user-1", "email": "user@example.com"}
PROJECT_SCHEMA = [
    {
        "name": "customers",
        "columns": [
            {"name": "id", "type": "bigint", "nullable": False, "is_primary_key": True},
            {"name": "name", "type": "text", "nullable": False, "is_primary_key": False},
            {"name": "email", "type": "text", "nullable": False, "is_primary_key": False},
            {"name": "status", "type": "text", "nullable": False, "is_primary_key": False},
        ],
        "primary_keys": ["id"],
        "foreign_keys": [],
    }
]


@pytest.fixture(autouse=True)
def authenticated_project(monkeypatch):
    project = {
        "id": "project-1",
        "owner_id": USER["id"],
        "name": "Test project",
        "database_url": "postgresql://demo:secret@example.com/demo",
        "schema_snapshot": PROJECT_SCHEMA,
        "allow_mutations": False,
    }

    def get_project(owner_id: str, project_id: str, *, include_database_url: bool = True):
        if owner_id != USER["id"] or project_id != project["id"]:
            raise HTTPException(status_code=404, detail="Project not found")
        return {**project, "schema_snapshot": PROJECT_SCHEMA}

    app.dependency_overrides[get_current_user_with_csrf] = lambda: USER
    monkeypatch.setattr(sql_routes, "get_owned_project", get_project)
    yield project
    app.dependency_overrides.clear()


class FakeCursor:
    def __init__(self, description=None, rows=None, rowcount=0):
        self.description = description
        self.rows = rows or []
        self.rowcount = rowcount
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchmany(self, size):
        return self.rows[:size]


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_value


def test_generate_sql_endpoint_returns_sql(monkeypatch):
    class FakeChatCompletions:
        def create(self, **kwargs):
            class FakeChoice:
                message = type("Msg", (), {"content": "```sql\nSELECT * FROM customers LIMIT 10;\n```"})()

            return type("Resp", (), {"choices": [FakeChoice()]})()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()

    monkeypatch.setattr(sql_routes, "OpenAI", FakeOpenAI)
    response = client.post(
        "/api/v1/sql/generate",
        json={"project_id": "project-1", "question": "Show me the first 10 customers"},
    )

    assert response.status_code == 200
    assert response.json()["sql"].strip().startswith("SELECT")


def test_generate_sql_uses_selected_project_schema(monkeypatch):
    captured = {}

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]

            class FakeChoice:
                message = type("Msg", (), {"content": "SELECT email FROM customers;"})()

            return type("Resp", (), {"choices": [FakeChoice()]})()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()

    monkeypatch.setattr(sql_routes, "OpenAI", FakeOpenAI)
    response = client.post(
        "/api/v1/sql/generate",
        json={"project_id": "project-1", "question": "List customer emails"},
    )

    assert response.status_code == 200
    assert "email" in captured["messages"][-1]["content"].lower()


def test_generate_sql_rejects_project_not_owned_by_user():
    response = client.post(
        "/api/v1/sql/generate",
        json={"project_id": "another-users-project", "question": "List customers"},
    )

    assert response.status_code == 404


def test_run_sql_endpoint_rejects_multiple_statements():
    response = client.post(
        "/api/v1/sql/run",
        json={"project_id": "project-1", "sql": "SELECT id FROM customers; DROP TABLE customers;"},
    )

    assert response.status_code == 400
    assert "one SQL statement" in response.json()["detail"]


def test_run_sql_endpoint_rejects_unknown_table_or_column():
    response = client.post(
        "/api/v1/sql/run",
        json={"project_id": "project-1", "sql": "SELECT missing_field FROM customers;"},
    )

    assert response.status_code == 400
    assert "missing_field" in response.json()["detail"]


def test_run_sql_rejects_tables_outside_imported_public_schema():
    response = client.post(
        "/api/v1/sql/run",
        json={"project_id": "project-1", "sql": "SELECT id FROM private.customers;"},
    )

    assert response.status_code == 400
    assert "public schema" in response.json()["detail"]


def test_run_sql_endpoint_allows_with_select_queries(monkeypatch):
    cursor = FakeCursor(description=[("id",), ("name",)], rows=[(1, "Alice")])
    monkeypatch.setattr(sql_routes, "connect_project_db", lambda database_url: FakeConnection(cursor))
    monkeypatch.setattr(
        sql_routes,
        "get_settings",
        lambda: SimpleNamespace(statement_timeout_ms=5000, max_result_rows=200),
    )
    response = client.post(
        "/api/v1/sql/run",
        json={
            "project_id": "project-1",
            "sql": "WITH recent AS (SELECT id, name FROM customers) SELECT id, name FROM recent;",
        },
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["id"] == 1
    assert cursor.executed[0][0] == "SET TRANSACTION READ ONLY"


def test_run_sql_requires_project_mutation_policy(authenticated_project):
    authenticated_project["allow_mutations"] = False
    response = client.post(
        "/api/v1/sql/run",
        json={
            "project_id": "project-1",
            "sql": "UPDATE customers SET status = 'active' WHERE id = 1;",
            "acknowledge_mutation": True,
        },
    )

    assert response.status_code == 403


def test_run_sql_requires_acknowledgement_for_mutations(monkeypatch, authenticated_project):
    authenticated_project["allow_mutations"] = True
    monkeypatch.setattr(sql_routes, "get_settings", lambda: SimpleNamespace(statement_timeout_ms=5000, max_result_rows=200))
    response = client.post(
        "/api/v1/sql/run",
        json={"project_id": "project-1", "sql": "UPDATE customers SET status = 'active' WHERE id = 1;"},
    )

    assert response.status_code == 409


def test_run_sql_rejects_full_table_mutations():
    response = client.post(
        "/api/v1/sql/run",
        json={
            "project_id": "project-1",
            "sql": "DELETE FROM customers;",
            "acknowledge_mutation": True,
        },
    )

    assert response.status_code == 400
    assert "WHERE" in response.json()["detail"]


def test_run_sql_executes_acknowledged_project_mutation(monkeypatch, authenticated_project):
    authenticated_project["allow_mutations"] = True
    cursor = FakeCursor(rowcount=1)
    monkeypatch.setattr(sql_routes, "connect_project_db", lambda database_url: FakeConnection(cursor))
    monkeypatch.setattr(sql_routes, "get_settings", lambda: SimpleNamespace(statement_timeout_ms=5000, max_result_rows=200))
    response = client.post(
        "/api/v1/sql/run",
        json={
            "project_id": "project-1",
            "sql": "UPDATE customers SET status = 'active' WHERE id = 1;",
            "acknowledge_mutation": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["row_count"] == 1
    assert cursor.executed[-1][0].startswith("UPDATE")


def test_run_sql_caps_project_query_results(monkeypatch):
    cursor = FakeCursor(description=[("id",)], rows=[(1,), (2,), (3,)])
    monkeypatch.setattr(sql_routes, "connect_project_db", lambda database_url: FakeConnection(cursor))
    monkeypatch.setattr(sql_routes, "get_settings", lambda: SimpleNamespace(statement_timeout_ms=5000, max_result_rows=2))
    response = client.post(
        "/api/v1/sql/run",
        json={"project_id": "project-1", "sql": "SELECT id FROM customers;"},
    )

    assert response.status_code == 200
    assert response.json()["rows"] == [{"id": 1}, {"id": 2}]
    assert response.json()["truncated"] is True
