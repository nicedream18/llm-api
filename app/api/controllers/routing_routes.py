"""Administrator route policy and dry-run diagnostics."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Path

from app.container import get_container
from app.domain.entities import ProxyRequestEntity
from app.types.routing import RoutePolicy, RoutePreview

router = APIRouter(prefix="/api/v1/routing", tags=["Routing"])


@router.get("/groups")
async def groups():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().routing_repo.groups)}


@router.put("/groups/{group}")
async def save_group(group: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[\w-]+$")], dto: RoutePolicy):
    await asyncio.to_thread(get_container().routing_repo.save_policy, group, dto.model_dump())
    return {"code": "0000", "info": "成功", "data": dto.model_dump()}


@router.post("/preview")
async def preview(dto: RoutePreview):
    request = ProxyRequestEntity(model=dto.model, body={}, endpoint=dto.endpoint, route_group=dto.route_group,
                                 principal_id=dto.principal_id, allowed_channels=frozenset(dto.allowed_channels))
    value = await asyncio.to_thread(get_container().gateway.routing.preview, request)
    return {"code": "0000", "info": "成功", "data": value}
