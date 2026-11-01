"""Wiki management API. Administrator authentication is enforced by middleware."""

import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.application.errors import ApplicationError
from app.application.services.wiki_service import (
    MAX_ASSET_BYTES,
    MAX_BACKUP_BYTES,
    page_view,
)
from app.container import get_container
from app.types.wiki import (
    WikiAskInput,
    WikiBackup,
    WikiPageInput,
    WikiPageUpdate,
    WikiProjectInput,
    WikiSourceInput,
)


def require_wiki_access(request: Request):
    context = getattr(request.state, "auth_context", None)
    if context is None:
        raise ApplicationError("Authentication required", 401, "authentication_error")
    if context.is_admin:
        return
    project_id = request.path_params.get("project_id")
    if project_id:
        get_container().access_service.require(context, "wiki", project_id)
    elif request.method not in {"GET", "HEAD"}:
        raise ApplicationError(
            "Administrator authentication required", 403, "permission_denied"
        )


router = APIRouter(
    prefix="/api/v1/wiki", tags=["Wiki"], dependencies=[Depends(require_wiki_access)]
)


def success(data=None):
    return {"code": "0000", "info": "成功", "data": data}


def service():
    return get_container().wiki_service


@router.get("/projects")
def list_projects(request: Request):
    rows = service().repo.list_projects()
    context = getattr(request.state, "auth_context", None)
    if not context.is_admin:
        allowed = get_container().access_service.allowed_resources(context, "wiki")
        rows = [row for row in rows if "*" in allowed or row["id"] in allowed]
    return success(rows)


@router.post("/projects", status_code=201)
def create_project(dto: WikiProjectInput):
    return success(service().repo.create_project(dto.model_dump()))


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    return success(service().repo.get_project(project_id))


@router.put("/projects/{project_id}")
def update_project(project_id: str, dto: WikiProjectInput):
    return success(service().repo.update_project(project_id, dto.model_dump()))


@router.delete("/projects/{project_id}")
def delete_project(project_id: str):
    service().repo.delete_project(project_id)
    return success()


@router.get("/projects/{project_id}/pages")
def list_pages(
    project_id: str,
    query: str = Query(default="", max_length=512),
    tag: str | None = Query(default=None, max_length=64),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    rows = service().list_pages(project_id, query, tag)
    return success({"items": rows[offset : offset + limit], "total": len(rows)})


@router.post("/projects/{project_id}/pages", status_code=201)
def create_page(project_id: str, dto: WikiPageInput):
    return success(service().create_page(project_id, dto))


@router.get("/projects/{project_id}/pages/{page_id}")
def get_page(project_id: str, page_id: str):
    return success(page_view(service().repo.get_page(project_id, page_id)))


@router.put("/projects/{project_id}/pages/{page_id}")
def update_page(project_id: str, page_id: str, dto: WikiPageUpdate):
    return success(service().update_page(project_id, page_id, dto))


@router.delete("/projects/{project_id}/pages/{page_id}")
def delete_page(project_id: str, page_id: str):
    service().repo.delete_page(project_id, page_id)
    return success()


@router.get("/projects/{project_id}/tags")
def tags(project_id: str):
    return success(service().tags(project_id))


@router.get("/projects/{project_id}/graph")
def graph(project_id: str):
    return success(service().graph(project_id))


@router.post("/projects/{project_id}/ask")
def ask(project_id: str, dto: WikiAskInput, request: Request):
    return success(
        service().ask(
            project_id,
            dto,
            getattr(request.state, "auth_context", None),
            getattr(request.state, "request_id", None),
        )
    )


@router.get("/projects/{project_id}/sources")
def sources(project_id: str):
    return success(
        [
            {key: value for key, value in row.items() if key != "content"}
            for row in service().repo.list_sources(project_id)
        ]
    )


@router.post("/projects/{project_id}/sources", status_code=201)
def create_source(project_id: str, dto: WikiSourceInput):
    row = service().repo.create_source(project_id, dto.model_dump())
    return success({key: value for key, value in row.items() if key != "content"})


@router.post("/projects/{project_id}/sources/{source_id}/ingest")
def ingest_source(project_id: str, source_id: str):
    return success(service().ingest(project_id, source_id))


@router.delete("/projects/{project_id}/sources/{source_id}")
def delete_source(project_id: str, source_id: str):
    service().repo.delete_source(project_id, source_id)
    return success()


async def bounded_body(request, limit):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            raise ApplicationError("Request exceeds size limit", 413, "size_limit")
        content.extend(chunk)
    return bytes(content)


@router.post("/projects/{project_id}/pages/{page_id}/attachments", status_code=201)
async def upload_attachment(
    project_id: str,
    page_id: str,
    request: Request,
    filename: str = Query(min_length=1, max_length=256),
):
    import asyncio

    content = await bounded_body(request, MAX_ASSET_BYTES)
    media_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    service().validate_asset(filename, media_type, content)
    row = await asyncio.to_thread(
        service().repo.add_attachment,
        project_id,
        page_id,
        filename,
        media_type,
        content,
    )
    return success(row)


@router.get("/projects/{project_id}/attachments/{attachment_id}")
def download_attachment(project_id: str, attachment_id: str):
    row = service().repo.get_attachment(project_id, attachment_id)
    return Response(
        row["content"],
        media_type=row["media_type"],
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(row["filename"], safe=""),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/projects/{project_id}/attachments/{attachment_id}")
def delete_attachment(project_id: str, attachment_id: str):
    service().repo.delete_attachment(project_id, attachment_id)
    return success()


@router.get("/projects/{project_id}/backup")
def export_backup(project_id: str):
    return JSONResponse(
        service().export(project_id),
        headers={
            "Content-Disposition": 'attachment; filename="wiki-backup.json"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/restore", status_code=201)
async def restore_backup(request: Request):
    import asyncio

    content = await bounded_body(request, MAX_BACKUP_BYTES)
    try:
        backup = WikiBackup.model_validate(json.loads(content))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, "Invalid Wiki backup") from exc
    restored = await asyncio.to_thread(service().restore, backup)
    return success(restored)
