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
