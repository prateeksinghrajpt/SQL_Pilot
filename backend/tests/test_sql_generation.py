from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_generate_sql_endpoint_returns_sql(monkeypatch):
    from app.api.routes import sql as sql_routes

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
        json={"question": "Show me the first 10 customers"},
    )

    assert response.status_code == 200
    assert response.json()["sql"].strip().startswith("SELECT")


def test_generate_sql_uses_schema_metadata_in_prompt(monkeypatch):
    from app.api.routes import sql as sql_routes

    captured = {}

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]

            class FakeChoice:
                message = type("Msg", (), {"content": "SELECT * FROM customers LIMIT 10;"})()

            return type("Resp", (), {"choices": [FakeChoice()]})()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = type("Chat", (), {"completions": FakeChatCompletions()})()

    monkeypatch.setattr(sql_routes, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(
        sql_routes,
        "fetch_schema_metadata",
        lambda: [
            {
                "name": "customers",
                "columns": [
                    {"name": "id", "type": "bigint", "nullable": False, "is_primary_key": True},
                    {"name": "email", "type": "text", "nullable": False, "is_primary_key": False},
                ],
                "primary_keys": ["id"],
                "foreign_keys": [],
            }
        ],
    )

    response = client.post(
        "/api/v1/sql/generate",
        json={"question": "Show the 10 most recent customers"},
    )

    assert response.status_code == 200
    prompt = captured["messages"][-1]["content"]
    assert "customers" in prompt.lower()
    assert "email" in prompt.lower()


def test_run_sql_endpoint_rejects_multiple_statements(monkeypatch):
    from app.api.routes import sql as sql_routes

    response = client.post(
        "/api/v1/sql/run",
        json={"sql": "SELECT id FROM customers; DROP TABLE customers;"},
    )

    assert response.status_code == 400
    assert "SELECT" in response.json()["detail"]


def test_run_sql_endpoint_rejects_unknown_table_or_column(monkeypatch):
    from app.api.routes import sql as sql_routes

    monkeypatch.setattr(
        sql_routes,
        "fetch_schema_metadata",
        lambda: [
            {
                "name": "customers",
                "columns": [
                    {"name": "id", "type": "bigint", "nullable": False, "is_primary_key": True},
                    {"name": "email", "type": "text", "nullable": False, "is_primary_key": False},
                ],
                "primary_keys": ["id"],
                "foreign_keys": [],
            }
        ],
    )

    response = client.post(
        "/api/v1/sql/run",
        json={"sql": "SELECT missing_field FROM customers;"},
    )

    assert response.status_code == 400
    assert "missing_field" in response.json()["detail"]


def test_run_sql_endpoint_executes_select_statement(monkeypatch):
    from app.api.routes import sql as sql_routes

    class FakeCursor:
        def __init__(self):
            self.description = [("id",), ("name",)]
            self.fetchall_result = [(1, "Alice"), (2, "Bob")]

        def execute(self, query):
            return None

        def fetchall(self):
            return self.fetchall_result

    class FakeConnection:
        def __init__(self):
            self.cursor_obj = FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return self.cursor_obj

    monkeypatch.setattr(sql_routes, "connect_db", lambda: FakeConnection())

    response = client.post(
        "/api/v1/sql/run",
        json={"sql": "SELECT id, name FROM customers LIMIT 2;"},
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["id"] == 1
    assert response.json()["rows"][0]["name"] == "Alice"
