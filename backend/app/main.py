from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.projects import router as projects_router
from app.api.routes.sql import router as sql_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="AI-Powered SQL Copilot API",
    description="Authenticated, schema-grounded SQL projects for PostgreSQL.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(sql_router, prefix="/api/v1")


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"name": "AI-Powered SQL Copilot API", "version": "0.1.0", "docs": "/docs"}
