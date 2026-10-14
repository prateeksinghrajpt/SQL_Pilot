import json
from types import SimpleNamespace

import duckdb
import pytest
from fastapi import HTTPException

from app.core import data_import


def test_csv_and_json_import_normalizes_tables_and_data(tmp_path):
    csv_tables = data_import.import_uploaded_files([
        ("Customer List.csv", "text/csv", b"Full Name,Age\nAsha,31\nRavi,28\n"),
    ])[0]
    json_tables = data_import.import_uploaded_files([
        ("orders.json", "application/json", json.dumps({"orders": [{"order id": 4, "total": 17.5}]}).encode()),
    ])[0]

    assert csv_tables[0]["name"] == "customer_list"
    assert csv_tables[0]["columns"][0]["name"] == "full_name"
    assert csv_tables[0]["rows"][1]["age"] == 28
    assert json_tables[0]["name"] == "orders"
    assert json_tables[0]["rows"][0]["order_id"] == 4

    database_path = str(tmp_path / "project.duckdb")
    schema = data_import.create_dataset(database_path, csv_tables + json_tables)
    assert [table["name"] for table in schema] == ["customer_list", "orders"]
    with duckdb.connect(database_path, read_only=True, config={"enable_external_access": "false"}) as connection:
        assert connection.execute('SELECT full_name, age FROM customer_list ORDER BY full_name').fetchall() == [
            ("Asha", 31),
            ("Ravi", 28),
        ]
        assert connection.execute("SELECT sum(age) FROM customer_list").fetchone() == (59,)
        assert connection.execute("SELECT order_id, total FROM orders").fetchall() == [(4, 17.5)]


def test_document_import_uses_structured_llm_extraction(monkeypatch):
    captured = {}
    settings = SimpleNamespace(openai_api_key="test-key", openai_organization=None, openai_model="test-model")
    monkeypatch.setattr(data_import, "get_settings", lambda: settings)

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            content = json.dumps({
                "tables": [{
                    "name": "inventory",
                    "columns": [{"name": "sku", "type": "text"}, {"name": "quantity", "type": "integer"}],
                    "rows": [{"sku": "A-1", "quantity": 7}],
                }]
            })
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(data_import, "OpenAI", FakeClient)
    tables, sources = data_import.import_uploaded_files([
        ("inventory.txt", "text/plain", b"SKU A-1 has quantity 7."),
    ])

    assert sources == ["inventory.txt"]
    assert tables[0]["name"] == "inventory"
    assert tables[0]["rows"] == [{"sku": "A-1", "quantity": 7}]
    assert captured["request"]["response_format"] == {"type": "json_object"}


def test_image_import_sends_image_to_structured_extractor(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        data_import,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key="test-key", openai_organization=None, openai_model="test-model"),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            payload = json.dumps({"tables": [{"name": "items", "columns": [{"name": "sku"}], "rows": [{"sku": "X1"}]}]})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(data_import, "OpenAI", FakeClient)
    tables, _sources = data_import.import_uploaded_files([("table.png", "image/png", b"fake-image-bytes")])

    image_part = captured["request"]["messages"][1]["content"][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert tables[0]["rows"] == [{"sku": "X1"}]


def test_import_rejects_unsupported_format():
    with pytest.raises(HTTPException) as error:
        data_import.import_uploaded_files([("dump.exe", "application/octet-stream", b"no")])

    assert error.value.status_code == 415


def test_schema_only_csv_import_creates_empty_table(tmp_path):
    tables, _sources = data_import.import_uploaded_files([
        ("empty_customers.csv", "text/csv", b"id,email\n"),
    ])
    schema = data_import.create_dataset(str(tmp_path / "empty.duckdb"), tables)

    assert schema[0]["columns"][0]["name"] == "id"
    assert schema[0]["row_count"] == 0
