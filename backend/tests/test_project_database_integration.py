import os
import uuid

import psycopg
import pytest

from app.core import projects

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="Set TEST_DATABASE_URL to a disposable PostgreSQL database")


def test_project_schema_import_reads_tables_columns_and_relationships(monkeypatch):
    monkeypatch.setattr(projects, "get_settings", lambda: type("Settings", (), {"allow_private_database_hosts": True})())
    suffix = uuid.uuid4().hex[:12]
    parent_table = f"copilot_it_{suffix}"
    child_table = f"copilot_it_child_{suffix}"

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(f'CREATE TABLE "{parent_table}" (id integer PRIMARY KEY, email text NOT NULL)')
        connection.execute(
            f'CREATE TABLE "{child_table}" (id integer PRIMARY KEY, customer_id integer REFERENCES "{parent_table}"(id))'
        )

    try:
        tables = projects.import_schema(TEST_DATABASE_URL)
        indexed = {table["name"]: table for table in tables}
        assert indexed[parent_table]["columns"][1]["name"] == "email"
        assert indexed[parent_table]["primary_keys"] == ["id"]
        assert indexed[child_table]["foreign_keys"] == [
            {"column": "customer_id", "references_table": parent_table, "references_column": "id"}
        ]
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(f'DROP TABLE IF EXISTS "{child_table}"')
            connection.execute(f'DROP TABLE IF EXISTS "{parent_table}"')
