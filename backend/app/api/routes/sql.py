from __future__ import annotations

import re
from typing import Any

import sqlglot
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlglot import exp

from app.api.routes.schema import fetch_schema_metadata
from app.core.config import get_settings

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

router = APIRouter(prefix="/sql", tags=["sql"])


class GenerateSqlRequest(BaseModel):
    question: str = Field(..., min_length=3)


class RunSqlRequest(BaseModel):
    sql: str = Field(..., min_length=6)


def _get_openai_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")
    if OpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed")
    return OpenAI(api_key=settings.openai_api_key, organization=settings.openai_organization)


def _normalize_sql_text(sql: str) -> str:
    cleaned = (sql or "").strip()
    cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    if cleaned.lower().startswith(("select", "with")):
        return cleaned

    match = re.search(r"(SELECT\b.*?;?|WITH\b.*?;?)", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()

    return cleaned


def _sanitize_sql(sql: str) -> str:
    cleaned = _normalize_sql_text(sql)
    if not cleaned:
        raise HTTPException(status_code=400, detail="SQL is empty")
    if ";" not in cleaned:
        cleaned += ";"
    return cleaned


def _normalize_identifier(value: str | None) -> str:
    if not value:
        return ""
    return value.strip('"`[]').lower()


def _validate_allowed_statement(sql: str) -> str:
    cleaned = _sanitize_sql(sql)

    if cleaned.count(";") > 1:
        raise HTTPException(
            status_code=400,
            detail="Only a single SELECT, INSERT, UPDATE, or DELETE statement is allowed for execution.",
        )

    try:
        parsed = sqlglot.parse_one(cleaned, read="postgres")
    except Exception as exc:  # pragma: no cover - invalid SQL is handled as a client error
        raise HTTPException(status_code=400, detail=f"Invalid SQL: {exc}") from exc

    allowed_types = (exp.Select, exp.Insert, exp.Update, exp.Delete)
    if not isinstance(parsed, allowed_types):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT, INSERT, UPDATE, and DELETE queries are allowed.",
        )

    try:
        schema_tables = fetch_schema_metadata()
    except Exception:
        return cleaned

    schema_lookup: dict[str, set[str]] = {}
    for table in schema_tables:
        table_name = _normalize_identifier(table.get("name"))
        if not table_name:
            continue
        schema_lookup[table_name] = {
            _normalize_identifier(column.get("name"))
            for column in table.get("columns", [])
            if column.get("name")
        }

    cte_aliases = {
        _normalize_identifier(cte.alias)
        for cte in parsed.find_all(exp.CTE)
        if getattr(cte, "alias", None)
    }
    tables_in_query: list[str] = []
    alias_map: dict[str, str] = {}
    for table_node in parsed.find_all(exp.Table):
        table_name = _normalize_identifier(table_node.name)
        if not table_name or table_name in cte_aliases:
            continue
        tables_in_query.append(table_name)
        if table_node.alias:
            alias_map[_normalize_identifier(table_node.alias_or_name)] = table_name

    for table_name in tables_in_query:
        if table_name not in schema_lookup:
            raise HTTPException(
                status_code=400,
                detail=f"Table '{table_name}' is not present in the current schema.",
            )

    for column_node in parsed.find_all(exp.Column):
        column_name = _normalize_identifier(column_node.name)
        if not column_name or column_name == "*":
            continue

        if column_node.table:
            table_ref = _normalize_identifier(column_node.table)
            if table_ref in cte_aliases:
                continue
            if table_ref in alias_map:
                table_ref = alias_map[table_ref]
            if table_ref not in schema_lookup or column_name not in schema_lookup[table_ref]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Column '{column_name}' does not exist on table '{table_ref}'.",
                )
            continue

        matches = [table for table in tables_in_query if column_name in schema_lookup.get(table, set())]
        if not matches:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{column_name}' does not exist in the selected schema.",
            )
        if len(matches) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{column_name}' is ambiguous across the selected tables.",
            )

    return cleaned


def _format_schema_context(tables: list[dict[str, Any]]) -> str:
    if not tables:
        return "No database schema metadata is available yet."

    lines: list[str] = []
    for table in tables:
        columns = table.get("columns", [])
        column_details = ", ".join(
            f"{column['name']} {column['type']}" + (" NULL" if column.get("nullable") else " NOT NULL")
            + (" PRIMARY KEY" if column.get("is_primary_key") else "")
            for column in columns
        )
        lines.append(f"- {table['name']} ({column_details})")

        if table.get("primary_keys"):
            lines.append(f"  PK: {', '.join(table['primary_keys'])}")

        if table.get("foreign_keys"):
            fk_parts = [
                f"{fk['column']} -> {fk['references_table']}.{fk['references_column']}"
                for fk in table["foreign_keys"]
            ]
            lines.append(f"  FK: {', '.join(fk_parts)}")

    return "\n".join(lines)


def connect_db():
    settings = get_settings()
    if psycopg is None:
        raise HTTPException(status_code=500, detail="psycopg is not installed")
    return psycopg.connect(settings.database_url, connect_timeout=3)


@router.post("/generate")
def generate_sql(payload: GenerateSqlRequest) -> dict[str, str]:
    client = _get_openai_client()
    settings = get_settings()
    try:
        schema_tables = fetch_schema_metadata()
    except Exception:
        schema_tables = []
    schema_context = _format_schema_context(schema_tables)

    prompt = (
        "Convert the user's request to a valid PostgreSQL query using the schema below. "
        "Use the exact table and column names from the schema. Return only the SQL statement and no extra explanation.\n\n"
        f"Schema:\n{schema_context}\n\nQuestion: {payload.question}"
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate PostgreSQL SQL from natural-language questions. "
                    "Use the provided schema metadata exactly and return only a SQL statement."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    sql = _normalize_sql_text(response.choices[0].message.content)
    if not sql:
        raise HTTPException(status_code=500, detail="Model returned empty SQL")
    return {"sql": sql, "question": payload.question}


@router.post("/run")
def run_sql(payload: RunSqlRequest) -> dict[str, Any]:
    sql = _validate_allowed_statement(payload.sql)

    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql)

        if cursor.description:
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            records = [dict(zip(columns, row, strict=False)) for row in rows]
            row_count = len(rows)
        else:
            columns = []
            records = []
            row_count = getattr(cursor, "rowcount", 0)

    response: dict[str, Any] = {"sql": sql, "columns": columns, "rows": records}
    if row_count is not None:
        response["row_count"] = row_count
    return response
