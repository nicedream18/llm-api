"""Prompt, semantic cache and application configuration routes."""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.container import get_container
from app.local_config import ClientConfigurations
from app.local_service import ManagedService
from app.types.platform import (
    AppConfigWriteInput,
    CacheLookupInput,
    CacheStoreInput,
    PromptRenderInput,
    PromptTemplateInput,
)

router = APIRouter(prefix="/api/v1/platform", tags=["Platform"])


class LocalConfigInput(BaseModel):
    home: str | None = None
    target: str = Field(min_length=1, max_length=32)
    url: str = "http://127.0.0.1:9900"
    allow_remote: bool = False
    expected_sha256: str | None = None
    backup_id: str | None = None


class LocalServiceInput(BaseModel):
    state_dir: str | None = None
    port: int = Field(default=9900, ge=1024, le=65535)


def _local_manager(home):
    return ClientConfigurations(home)


@router.get("/prompts")
async def list_prompts():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.list_prompts)}


@router.post("/prompts")
async def create_prompt(dto: PromptTemplateInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.create_prompt, dto)}


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, dto: PromptTemplateInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.update_prompt, prompt_id, dto)}


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.delete_prompt, prompt_id)}


@router.post("/prompts/{prompt_id}/render")
async def render_prompt(prompt_id: str, dto: PromptRenderInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.render_prompt, prompt_id, dto.variables)}


@router.post("/cache/get")
async def cache_get(dto: CacheLookupInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.cache_get, dto.model, dto.request, dto.scope)}


@router.post("/cache/put")
async def cache_put(dto: CacheStoreInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.cache_put, dto.model, dto.request, dto.response, dto.scope, dto.ttl_seconds)}


@router.delete("/cache")
async def cache_clear():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.clear_cache)}


@router.post("/config/preview")
async def config_preview(dto: AppConfigWriteInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.preview_config, dto.target, dto.values)}


@router.get("/config")
async def config_list():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.list_configs)}


@router.post("/config/write")
async def config_write(dto: AppConfigWriteInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.write_config, dto.target, dto.values)}


@router.delete("/config/{target}")
async def config_delete(target: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().platform_service.delete_config, target)}


@router.post("/local/config/detect")
async def local_config_detect(home: str | None = Query(None, max_length=1024)):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(_local_manager(home).detect)}


@router.post("/local/config/preview")
async def local_config_preview(dto: LocalConfigInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(_local_manager(dto.home).preview, dto.target, dto.url, dto.allow_remote)}


@router.post("/local/config/apply")
async def local_config_apply(dto: LocalConfigInput):
    if not dto.expected_sha256:
        raise HTTPException(422, "expected_sha256 from preview is required")
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(_local_manager(dto.home).apply, dto.target, dto.expected_sha256, dto.url, dto.allow_remote)}


@router.post("/local/config/restore")
async def local_config_restore(dto: LocalConfigInput):
    if not dto.backup_id:
        raise HTTPException(422, "backup_id is required")
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(_local_manager(dto.home).restore, dto.target, dto.backup_id)}


@router.get("/local/service")
async def local_service_status(state_dir: str | None = Query(None, max_length=1024)):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(ManagedService(state_dir).status)}


@router.post("/local/service/start")
async def local_service_start(dto: LocalServiceInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(ManagedService(dto.state_dir).start, dto.port)}


@router.post("/local/service/stop")
async def local_service_stop(state_dir: str | None = Query(None, max_length=1024)):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(ManagedService(state_dir).stop)}
