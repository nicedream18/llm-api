"""Administrator provider account management routes."""

import asyncio

from fastapi import APIRouter

from app.container import get_container
from app.types.provider import ProviderAccountInput, ProviderTokenInput

router = APIRouter(prefix="/api/v1/providers", tags=["Providers"])


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
async def authorize_provider(account_id: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.authorize, account_id)}


@router.post("/callback/{provider}")
async def provider_callback(provider: str, state: str, code: str):
    return {"code": "0000", "info": "成功", "data": await asyncio.to_thread(get_container().provider_service.callback, state, code)}


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
