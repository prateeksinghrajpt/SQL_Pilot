from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.core.data_import import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from app.core.projects import (
    create_project,
    delete_project,
    get_owned_project,
    list_projects,
    public_project,
    refresh_project_schema,
    update_project,
)
from app.core.security import get_current_user, get_current_user_with_csrf

router = APIRouter(prefix="/projects", tags=["projects"])


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    allow_mutations: bool | None = None


@router.get("")
def get_projects(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"projects": list_projects(user["id"])}


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_project(
    name: str = Form(min_length=1, max_length=80),
    files: list[UploadFile] = File(min_length=1, max_length=10),
    user: dict[str, Any] = Depends(get_current_user_with_csrf),
) -> dict[str, Any]:
    uploads = []
    total_size = 0
    for uploaded_file in files:
        content = await uploaded_file.read(MAX_FILE_BYTES + 1)
        await uploaded_file.close()
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"File '{uploaded_file.filename}' exceeds the 20 MB limit")
        total_size += len(content)
        if total_size > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="The total upload size exceeds 50 MB")
        uploads.append((uploaded_file.filename or "upload", uploaded_file.content_type or "", content))
    project = create_project(user["id"], name, uploads)
    return {"project": public_project(project)}


@router.get("/{project_id}")
def get_project(project_id: str, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"project": public_project(get_owned_project(user["id"], project_id))}


@router.patch("/{project_id}")
def patch_project(
    project_id: str,
    payload: UpdateProjectRequest,
    user: dict[str, Any] = Depends(get_current_user_with_csrf),
) -> dict[str, Any]:
    if payload.name is None and payload.allow_mutations is None:
        raise HTTPException(status_code=422, detail="Provide a project name or mutation policy")
    project = update_project(
        user["id"],
        project_id,
        name=payload.name,
        allow_mutations=payload.allow_mutations,
    )
    return {"project": project}


@router.post("/{project_id}/refresh-schema")
def post_refresh_schema(
    project_id: str,
    user: dict[str, Any] = Depends(get_current_user_with_csrf),
) -> dict[str, Any]:
    return {"project": refresh_project_schema(user["id"], project_id)}


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project(
    project_id: str,
    user: dict[str, Any] = Depends(get_current_user_with_csrf),
) -> Response:
    delete_project(user["id"], project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
