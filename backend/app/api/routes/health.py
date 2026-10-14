import sqlite3

from fastapi import APIRouter, HTTPException

from app.db import auth_store

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    # Liveness: confirms the API process is responding.
    return {"status": "ok", "service": "sql-copilot-api", "version": "0.1.0"}


@router.get("/ready")
def readiness() -> dict[str, str]:
    try:
        with auth_store.connection():
            pass
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="Project storage is not ready") from exc
    return {"status": "ready", "storage": "connected"}
