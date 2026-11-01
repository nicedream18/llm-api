"""Prompt, semantic cache and application configuration routes."""

from fastapi import APIRouter

from app.container import get_container
from app.types.platform import (
    AppConfigWriteInput,
    CacheLookupInput,
    CacheStoreInput,
    PromptRenderInput,
    PromptTemplateInput,
)

router = APIRouter(prefix="/api/v1/platform", tags=["Platform"])


@router.get("/prompts")
async def list_prompts():
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.list_prompts()}


@router.post("/prompts")
async def create_prompt(dto: PromptTemplateInput):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.create_prompt(dto)}


@router.put("/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, dto: PromptTemplateInput):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.update_prompt(prompt_id, dto)}


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.delete_prompt(prompt_id)}


@router.post("/prompts/{prompt_id}/render")
async def render_prompt(prompt_id: str, dto: PromptRenderInput):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.render_prompt(prompt_id, dto.variables)}


@router.post("/cache/get")
async def cache_get(dto: CacheLookupInput):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.cache_get(dto.model, dto.request, dto.scope)}


@router.post("/cache/put")
async def cache_put(dto: CacheStoreInput):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.cache_put(dto.model, dto.request, dto.response, dto.scope, dto.ttl_seconds)}


@router.delete("/cache")
async def cache_clear():
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.clear_cache()}


@router.post("/config/preview")
async def config_preview(dto: AppConfigWriteInput):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.preview_config(dto.target, dto.values)}


@router.get("/config")
async def config_list():
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.list_configs()}


@router.post("/config/write")
async def config_write(dto: AppConfigWriteInput):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.write_config(dto.target, dto.values)}


@router.delete("/config/{target}")
async def config_delete(target: str):
    return {"code": "0000", "info": "成功", "data": get_container().platform_service.delete_config(target)}
