from fastapi import APIRouter, HTTPException
from psycopg import OperationalError

from app.db.connection import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    # Liveness: confirms the API process is responding.
    return {"status": "ok", "service": "sql-copilot-api", "version": "0.1.0"}


@router.get("/ready")
def readiness() -> dict[str, str]:
    # Readiness: confirms the API can connect to PostgreSQL.
    try:
        check_database_connection()
    except (OperationalError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Database is not ready") from exc
    return {"status": "ready", "database": "connected"}
