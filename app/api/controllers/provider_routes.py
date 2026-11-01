"""Administrator provider account management routes."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.container import get_container
from app.domain.provider_adapters import ConfiguredProviderAdapter
from app.types.provider import (
    PROVIDER_NAMES,
    ProviderAccountInput,
    ProviderAccountQuery,
    ProviderBulkInput,
    ProviderOperationInput,
    ProviderTokenInput,
)
from app.types.provider_sync import ProviderSyncInput, ProviderSyncSettings

router = APIRouter(prefix="/api/v1/providers", tags=["Providers"])


def _principal(request):
    context = getattr(request.state, "auth_context", None)
    return (context.principal_type, context.principal_id) if context else ("admin", "system")


@router.get("/capabilities")
async def provider_capabilities():
    return {"code": "0000", "info": "成功", "data": [{"provider": name, "adapter": ConfiguredProviderAdapter.__name__, "mode": "configured_oauth", "vendor_verified": False} for name in PROVIDER_NAMES]}


@router.get("/accounts")
async def query_accounts(query: Annotated[ProviderAccountQuery, Depends()]):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.query_accounts, query)}


@router.get("/{account_id}/sync")
async def synchronization_state(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.sync_state, account_id)}


@router.post("/{account_id}/sync", status_code=202)
async def enqueue_sync(account_id: str, dto: ProviderSyncInput):
    repo = get_container().provider_repo
    jobs = [await asyncio.to_thread(repo.enqueue_sync, account_id, kind) for kind in dict.fromkeys(dto.kinds)]
    return {"code": "0000", "info": "成功", "data": {"jobs": jobs}}


@router.put("/{account_id}/sync/settings")
async def configure_sync(account_id: str, dto: ProviderSyncSettings):
    await asyncio.to_thread(get_container().provider_repo.configure_sync, account_id, dto.model_dump())
    return {"code": "0000", "info": "成功", "data": dto.model_dump()}


@router.post("/bulk")
async def bulk_accounts(dto: ProviderBulkInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.bulk_accounts, dto)}


@router.post("/{account_id}/operations")
async def operate_account(account_id: str, dto: ProviderOperationInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.operate_account, account_id, dto)}


@router.get("/{account_id}/events")
async def account_events(account_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    service = get_container().provider_service
    await asyncio.to_thread(service.account_detail, account_id)
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(service.repo.account_events, account_id, limit, offset)}


@router.get("/{account_id}")
async def account_detail(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.account_detail, account_id)}


@router.get("")
async def list_providers():
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.list_accounts)}


@router.post("")
async def create_provider(dto: ProviderAccountInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.create_account, dto)}


@router.put("/{account_id}")
async def update_provider(account_id: str, dto: ProviderAccountInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.update_account, account_id, dto)}


@router.delete("/{account_id}")
async def delete_provider(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.delete_account, account_id)}


@router.post("/{account_id}/token")
async def set_provider_token(account_id: str, dto: ProviderTokenInput):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.set_token, account_id, dto)}


@router.post("/{account_id}/authorize")
async def authorize_provider(account_id: str, request: Request):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.authorize, account_id, _principal(request))}


@router.api_route("/callback/{provider}", methods=["GET", "POST"])
async def provider_callback(provider: str, request: Request, state: str = Query(min_length=16, max_length=256), code: str = Query(default="", max_length=16384), error: str | None = Query(default=None, max_length=256)):
    request.scope["query_string"] = b""
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.callback, state, code, _principal(request), provider, error)}


@router.post("/{account_id}/refresh")
async def refresh_provider(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.refresh, account_id)}


@router.post("/{account_id}/logout")
async def logout_provider(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.sign_out, account_id)}


@router.get("/{account_id}/quota")
async def provider_quota(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.quota, account_id)}


@router.get("/{account_id}/models")
async def provider_models(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.models, account_id)}
