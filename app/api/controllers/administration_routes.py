"""Protected diagnostics and bounded administrative audit queries."""

import asyncio
import platform

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.container import get_container
from app.infrastructure.database.connection import engine
from app.infrastructure.database.migrations import status

router = APIRouter(prefix="/api/v1/administration", tags=["Administration"])


def audit_rows(limit, offset, action):
    with engine.connect() as db:
        return [dict(row) for row in db.execute(text("""SELECT id,username,action,request_id,client_ip,success,created_at
            FROM admin_audit_logs WHERE (:action='' OR action=:action)
            ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"""), {"action": action, "limit": limit, "offset": offset}).mappings()]


@router.get("/audit")
async def audit(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=1_000_000), action: str = Query("", max_length=128)):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(audit_rows, limit, offset, action)}


def diagnostics_data():
    result = {"python": platform.python_version(), "database": "unavailable", "migrations": "unavailable"}
    try:
        with engine.connect() as db:
            db.execute(text("SELECT 1"))
        result["database"] = "ok"
        rows = status()
        result["migrations"] = "ok" if rows and all(row["applied"] and row["checksum_valid"] for row in rows) else "pending_or_invalid"
    except Exception:  # noqa: BLE001 - diagnostics returns safe availability, never connection details
        result["migrations"] = "unavailable"
    return result


@router.get("/diagnostics")
async def diagnostics():
    container = get_container()
    data = await asyncio.to_thread(diagnostics_data)
    data["http_client"] = "closed" if container.gateway.client.is_closed else "open"
    data["workers"] = {"knowledge": bool(container.kb_worker.running),
                       "provider_sync": bool(container.provider_sync_worker.running),
                       "operations": bool(container.operations_worker.task and not container.operations_worker.task.done())}
    return {"code": "0000", "info": "成功", "data": data}


def metric_text():
    with engine.connect() as db:
        values = dict(db.execute(text("SELECT kind,COUNT(*) FROM usage_ledger GROUP BY kind")).all())
    return "# TYPE waliapi_usage_events counter\n" + "".join(f'waliapi_usage_events{{kind="{kind}"}} {int(values.get(kind, 0))}\n' for kind in ("attempt", "outcome"))


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(await asyncio.to_thread(metric_text), media_type="text/plain; version=0.0.4")
