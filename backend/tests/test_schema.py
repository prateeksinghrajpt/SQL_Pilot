from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_schema_endpoint_returns_tables(monkeypatch):
    from app.api.routes import schema as schema_routes

    monkeypatch.setattr(
        schema_routes,
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
            },
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "type": "bigint", "nullable": False, "is_primary_key": True},
                    {"name": "customer_id", "type": "bigint", "nullable": False, "is_primary_key": False},
                ],
                "primary_keys": ["id"],
                "foreign_keys": [
                    {"column": "customer_id", "references_table": "customers", "references_column": "id"}
                ],
            },
        ],
    )

    response = client.get("/api/v1/schema")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tables"][0]["name"] == "customers"
    assert payload["tables"][1]["foreign_keys"][0]["references_table"] == "customers"
