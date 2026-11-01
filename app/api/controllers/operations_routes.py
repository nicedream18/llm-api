"""Protected analytics, drill-down and internal alert operations."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from app.container import get_container
from app.types.analytics import AlertRule, AnalyticsQuery

router = APIRouter(prefix="/api/v1/operations", tags=["Operations"])


@router.get("/analytics")
async def analytics(query: Annotated[AnalyticsQuery, Query()]):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().analytics_repo.report, query)}


@router.get("/events")
async def events(query: Annotated[AnalyticsQuery, Query()]):
    # Fixed first page; pagination is provided separately to keep the typed
    # filter model free from ambiguous extra query fields.
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().analytics_repo.events, query)}


@router.post("/events/query")
async def query_events(query: AnalyticsQuery, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1_000_000)):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().analytics_repo.events, query, limit, offset)}


@router.get("/alerts")
async def alerts(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1_000_000)):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().alert_repo.list, limit, offset)}


@router.get("/alerts/rules")
async def rules():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().alert_repo.rules)}


@router.put("/alerts/rules/{rule_id}")
async def save_rule(rule_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")], dto: AlertRule):
    await asyncio.to_thread(get_container().alert_repo.save_rule, rule_id, dto.model_dump())
    return {"code": "0000", "info": "成功", "data": dto.model_dump()}


@router.post("/alerts/evaluate")
async def evaluate():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().operations_service.evaluate)}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge(alert_id: str, request: Request):
    context = getattr(request.state, "auth_context", None)
    value = await asyncio.to_thread(get_container().alert_repo.acknowledge, alert_id, context.principal_id if context else "admin")
    return {"code": "0000", "info": "成功", "data": {"changed": value}}
