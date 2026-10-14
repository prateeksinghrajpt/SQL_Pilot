from __future__ import annotations

import re
from typing import Any

import sqlglot
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlglot import exp

from app.core.projects import connect_project_db, get_owned_project
from app.core.config import get_settings
from app.core.security import get_current_user_with_csrf

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

router = APIRouter(prefix="/sql", tags=["sql"])


class GenerateSqlRequest(BaseModel):
    project_id: str = Field(min_length=1)
    question: str = Field(..., min_length=3)


class RunSqlRequest(BaseModel):
    project_id: str = Field(min_length=1)
    sql: str = Field(..., min_length=6)
    acknowledge_mutation: bool = False


def _get_openai_client() -> Any:
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

    if cleaned.lower().startswith(("select", "with", "insert", "update", "delete")):
        return cleaned

    match = re.search(r"\b(?:SELECT|WITH|INSERT|UPDATE|DELETE)\b.*", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0).strip()

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


def _validate_allowed_statement(sql: str, schema_tables: list[dict[str, Any]]) -> tuple[str, exp.Expression]:
    cleaned = _sanitize_sql(sql)

    try:
        statements = [statement for statement in sqlglot.parse(cleaned, read="postgres") if statement is not None]
    except Exception as exc:  # pragma: no cover - invalid SQL is handled as a client error
        raise HTTPException(status_code=400, detail=f"Invalid SQL: {exc}") from exc
    if len(statements) != 1:
        raise HTTPException(status_code=400, detail="Only one SQL statement is allowed for execution.")
    parsed = statements[0]

    allowed_types = (exp.Select, exp.Insert, exp.Update, exp.Delete)
    if not isinstance(parsed, allowed_types):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT, INSERT, UPDATE, and DELETE queries are allowed.",
        )
    if isinstance(parsed, (exp.Update, exp.Delete)) and parsed.args.get("where") is None:
        raise HTTPException(status_code=400, detail="UPDATE and DELETE statements must include a WHERE clause.")

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
        schema_name = _normalize_identifier(table_node.db)
        if schema_name and schema_name != "public":
            raise HTTPException(status_code=400, detail="Only tables in the imported public schema are allowed.")
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

    return cleaned, parsed


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


@router.post("/generate")
def generate_sql(
    payload: GenerateSqlRequest,
    user: dict[str, Any] = Depends(get_current_user_with_csrf),
) -> dict[str, str]:
    project = get_owned_project(user["id"], payload.project_id, include_database_url=False)
    client = _get_openai_client()
    settings = get_settings()
    schema_context = _format_schema_context(project["schema_snapshot"])

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
def run_sql(
    payload: RunSqlRequest,
    user: dict[str, Any] = Depends(get_current_user_with_csrf),
) -> dict[str, Any]:
    project = get_owned_project(user["id"], payload.project_id)
    sql, statement = _validate_allowed_statement(payload.sql, project["schema_snapshot"])
    is_mutation = isinstance(statement, (exp.Insert, exp.Update, exp.Delete))
    if is_mutation and not project["allow_mutations"]:
        raise HTTPException(status_code=403, detail="Data-changing queries are disabled for this project.")
    if is_mutation and not payload.acknowledge_mutation:
        raise HTTPException(status_code=409, detail="Explicit acknowledgement is required for data-changing queries.")
    settings = get_settings()

    with connect_project_db(project["database_url"]) as conn:
        cursor = conn.cursor()
        if isinstance(statement, exp.Select):
            cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SELECT set_config('statement_timeout', %s, true)", (f"{settings.statement_timeout_ms}ms",))
        cursor.execute(sql)

        if cursor.description:
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchmany(settings.max_result_rows + 1)
            truncated = len(rows) > settings.max_result_rows
            rows = rows[:settings.max_result_rows]
            records = [dict(zip(columns, row, strict=False)) for row in rows]
            row_count = len(records)
        else:
            columns = []
            records = []
            row_count = getattr(cursor, "rowcount", 0)
            truncated = False

    response: dict[str, Any] = {"sql": sql, "columns": columns, "rows": records}
    if row_count is not None:
        response["row_count"] = row_count
    if truncated:
        response["truncated"] = True
    return response
