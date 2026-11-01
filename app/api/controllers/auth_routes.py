import asyncio

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.application.services.auth_service import AuthError
from app.config import config
from app.container import get_container

router = APIRouter(prefix="/api/v1/auth")

class LoginDTO(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)

class PasswordDTO(BaseModel):
    password: str = Field(min_length=12, max_length=512)

@router.post('/login')
async def login(dto: LoginDTO, request: Request, response: Response):
    try:
        token = await asyncio.to_thread(get_container().admin_service.login,
            dto.username, dto.password,
            request.client.host if request.client else None,
            getattr(request.state, 'request_id', None),
        )
        response.set_cookie('waliapi_admin_session', token, httponly=True, secure=config.auth.session_cookie_secure, samesite='lax', max_age=config.auth.session_ttl_seconds, path='/')
        return {'code':'0000','info':'成功','data':{'username':config.auth.admin_username}}
    except AuthError as exc:
        return JSONResponse(status_code=exc.status_code, content={'code':'0008','info':'未授权访问','data':None})

@router.post('/logout')
async def logout(request: Request, response: Response):
    context = request.state.auth_context
    await asyncio.to_thread(get_container().admin_service.logout, request.cookies.get('waliapi_admin_session'))
    get_container().admin_service.audit(context.principal_name, "logout", getattr(request.state, 'request_id', None), request.client.host if request.client else None)
    response.delete_cookie('waliapi_admin_session', path='/')
    return {'code':'0000','info':'成功','data':None}

@router.get('/session')
async def session(request: Request):
    ctx = getattr(request.state, 'auth_context', None)
    return {'code':'0000','info':'成功','data':{'authenticated':bool(ctx and ctx.is_admin), 'username':ctx.principal_name if ctx else None}}

@router.post('/change-password')
async def change_password(dto: PasswordDTO, request: Request):
    ctx = request.state.auth_context
    await asyncio.to_thread(get_container().admin_service.change_password, ctx.principal_name or 'admin', dto.password, getattr(request.state, 'request_id', None), request.client.host if request.client else None)
    response = JSONResponse({'code':'0000','info':'成功','data':None})
    response.delete_cookie('waliapi_admin_session', path='/')
    return response


@router.get('/sessions')
async def sessions(request: Request):
    data = await asyncio.to_thread(get_container().admin_service.sessions.sessions, request.state.auth_context.principal_name)
    return {'code': '0000', 'info': '成功', 'data': data}


@router.delete('/sessions/{session_id}')
async def revoke_session(session_id: str, request: Request):
    service = get_container().admin_service
    if not await asyncio.to_thread(service.sessions.revoke, request.state.auth_context.principal_name, session_id):
        raise HTTPException(404, 'Session not found')
    await asyncio.to_thread(service.audit, request.state.auth_context.principal_name, 'session_revoked', getattr(request.state, 'request_id', None), request.client.host if request.client else None)
    return {'code': '0000', 'info': '成功', 'data': True}
