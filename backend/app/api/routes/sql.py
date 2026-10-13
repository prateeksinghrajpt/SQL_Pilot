from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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


def connect_db():
    settings = get_settings()
    if psycopg is None:
        raise HTTPException(status_code=500, detail="psycopg is not installed")
    return psycopg.connect(settings.database_url, connect_timeout=3)


@router.post("/generate")
def generate_sql(payload: GenerateSqlRequest) -> dict[str, str]:
    client = _get_openai_client()
    settings = get_settings()

    prompt = (
        "Convert the user's request to a valid PostgreSQL query. "
        "Return only the SQL statement and no extra explanation.\n\n"
        f"Question: {payload.question}"
    )

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "You generate PostgreSQL SQL from natural-language questions."},
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
    sql = _sanitize_sql(payload.sql)

    if not sql.lower().startswith(("select", "with")):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed in this phase")

    with connect_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in (cursor.description or [])]
        rows = cursor.fetchall()

    records = [dict(zip(columns, row, strict=False)) for row in rows]
    return {"sql": sql, "columns": columns, "rows": records}
