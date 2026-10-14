import sqlite3

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_returns_service_metadata() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "AI-Powered SQL Copilot API"
    assert response.json()["docs"] == "/docs"


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sql-copilot-api",
        "version": "0.1.0",
    }


def test_readiness_endpoint_reports_project_storage_unavailable(monkeypatch) -> None:
    from app.api.routes import health

    def fail_connection() -> None:
        raise sqlite3.OperationalError("storage unavailable")

    monkeypatch.setattr(health.auth_store, "connection", fail_connection)
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Project storage is not ready"
