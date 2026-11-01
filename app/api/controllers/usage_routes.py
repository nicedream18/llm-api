"""Protected immutable usage and versioned pricing APIs."""

import asyncio

from fastapi import APIRouter

from app.container import get_container
from app.types.usage import PriceInput

router = APIRouter(prefix="/api/v1/usage", tags=["Usage"])


@router.get("/prices")
async def prices():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().usage_repo.prices)}


@router.post("/prices", status_code=201)
async def add_price(dto: PriceInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().usage_repo.add_price, dto)}


@router.get("/requests/{request_id}")
async def request_facts(request_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().usage_repo.by_request, request_id)}
