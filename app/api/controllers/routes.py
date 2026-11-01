"""All FastAPI route controllers."""
import asyncio
import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.resource_dependencies import require_kb_access
from app.application.services.misc_services import RawProxyResponse
from app.config import config
from app.container import get_container
from app.infrastructure.database.connection import engine
from app.infrastructure.database.migrations import status as migration_status
from app.types.models import (
    AgentChatRequestDTO,
    AgentConfigDTO,
    ApiKeyDTO,
    ChannelApiKeyDTO,
    ChannelDTO,
    CreateKbDTO,
    KbAskRequestDTO,
    KbKnowledgeBaseDTO,
    KbSearchRequestDTO,
    SecurityCustomRuleDTO,
    UploadDocDTO,
)
from app.types.software import (
    SoftwareInstanceInput,
    SoftwareInvokeInput,
    SoftwareToolInput,
)

logger = logging.getLogger(__name__)


def _success(data=None):
    return {"code": "0000", "info": "\u6210\u529f", "data": data}


# ==================== Gateway Controller ====================

gateway_router = APIRouter()


@gateway_router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    container = get_container()
    body = await request.body()
    body_str = body.decode("utf-8")
    headers = {k.lower(): v for k, v in request.headers.items()}
    accept = request.headers.get("accept", "")
    is_stream = ("text/event-stream" in accept) or ('"stream"' in body_str and "true" in body_str.lower())
    if is_stream:
        return StreamingResponse(
            container.proxy_service.forward_stream_async(body_str, headers, client_ip=request.client.host if request.client else None, auth_context=getattr(request.state, "auth_context", None), endpoint=str(request.url.path), request_id=getattr(request.state, "request_id", None)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    status, result = await asyncio.to_thread(container.proxy_service.forward, body_str, headers, client_ip=request.client.host if request.client else None, auth_context=getattr(request.state, "auth_context", None), endpoint=str(request.url.path), request_id=getattr(request.state, "request_id", None))
    if isinstance(result, RawProxyResponse):
        response_headers = dict(result.headers or {})
        if result.media_type:
            response_headers.setdefault("Content-Type", result.media_type)
        return Response(content=result.content, status_code=status, headers=response_headers)
    return JSONResponse(status_code=status, content=result)


@gateway_router.post("/v1/completions")
@gateway_router.post("/v1/responses")
@gateway_router.post("/v1/messages")
@gateway_router.post("/v1/embeddings")
@gateway_router.post("/v1/images/generations")
@gateway_router.post("/v1/audio/transcriptions")
@gateway_router.post("/v1/audio/speech")
async def proxy_generic(request: Request):
    container = get_container()
    raw_body = await request.body()
    content_type = request.headers.get("content-type", "")
    headers = {k.lower(): v for k, v in request.headers.items()}
    body = raw_body if content_type.lower().startswith("multipart/") else raw_body.decode("utf-8")
    is_stream = "text/event-stream" in request.headers.get("accept", "") or b'"stream"' in raw_body.lower() and b"true" in raw_body.lower()
    if is_stream:
        return StreamingResponse(
            container.proxy_service.forward_stream_async(body, headers, client_ip=request.client.host if request.client else None, auth_context=getattr(request.state, "auth_context", None), endpoint=str(request.url.path), request_id=getattr(request.state, "request_id", None)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    status, result = await asyncio.to_thread(container.proxy_service.forward, body, headers, client_ip=request.client.host if request.client else None, auth_context=getattr(request.state, "auth_context", None), endpoint=str(request.url.path), request_id=getattr(request.state, "request_id", None), content_type=content_type)
    if isinstance(result, RawProxyResponse):
        response_headers = dict(result.headers or {})
        if result.media_type:
            response_headers.setdefault("Content-Type", result.media_type)
        return Response(content=result.content, status_code=status, headers=response_headers)
    return JSONResponse(status_code=status, content=result)


@gateway_router.get("/v1/models")
async def models(request: Request):
    context = getattr(request.state, "auth_context", None)
    channels = get_container().channel_repo.get_enabled_channels()
    names: set[str] = set()
    for channel in channels:
        if context and context.is_api_key and context.allowed_channels and channel.id not in context.allowed_channels and channel.name not in context.allowed_channels:
            continue
        names.update(channel.models or [])
    if context and context.is_api_key and context.allowed_models:
        names.intersection_update(context.allowed_models)
    if not names and not context:
        names.add("gpt-4o")
    return {"object": "list", "data": [{"id": name, "object": "model", "owned_by": "waliapi"} for name in sorted(names)]}


@gateway_router.get("/health")
@gateway_router.get("/api/v1/health")
async def health():
    return {"status": "ok", "service": "WaLiAPI-Python", "version": "1.0.0"}


@gateway_router.get("/api/v1/health/details")
async def health_details():
    container = get_container()
    details = {"database": "ok", "migration": "unknown", "http_client": "ok",
               "worker": "running" if container.kb_worker.running else "stopped"}
    try:
        with engine.connect() as db:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
        rows = migration_status()
        details["migration"] = "ok" if all(item["checksum_valid"] for item in rows) else "invalid"
    except Exception:  # noqa: BLE001 - health endpoint must report degraded state
        details["database"] = "error"
        details["migration"] = "error"
    try:
        details["enabled_channels"] = len(container.channel_repo.get_enabled_channels())
    except Exception:  # noqa: BLE001 - health endpoint must report degraded state
        details["enabled_channels"] = None
    try:
        with engine.connect() as db:
            task_counts = db.execute(__import__("sqlalchemy").text("SELECT status, COUNT(*) AS total FROM kb_tasks GROUP BY status")).mappings().all()
        details["tasks"] = {row["status"]: int(row["total"]) for row in task_counts}
    except Exception:  # noqa: BLE001 - health endpoint must report degraded state
        details["tasks"] = None
    details["security_rules"] = "loaded" if config.security.enabled else "disabled"
    details["http_client"] = "closed" if container.gateway.client.is_closed else "open"
    return {"status": "ok" if details["database"] == "ok" and details["migration"] == "ok" else "degraded", "checks": details}


# ==================== Channel Controller ====================

channel_router = APIRouter(prefix="/api/v1/channels")


@channel_router.get("")
async def list_channels():
    return _success(get_container().channel_service.list_channels())


@channel_router.get("/{channel_id}")
async def get_channel(channel_id: str):
    return _success(get_container().channel_service.get_channel(channel_id))


@channel_router.post("")
async def create_channel(dto: ChannelDTO):
    return _success(get_container().channel_service.create_channel(dto))


@channel_router.put("")
async def update_channel(dto: ChannelDTO):
    return _success(get_container().channel_service.update_channel(dto))


@channel_router.delete("/{channel_id}")
async def delete_channel(channel_id: str):
    return _success(get_container().channel_service.delete_channel(channel_id))


@channel_router.post("/{channel_id}/test")
async def test_channel(channel_id: str):
    return _success(await asyncio.to_thread(get_container().channel_service.test_channel, channel_id))


@channel_router.post("/{channel_id}/clone")
async def clone_channel(channel_id: str):
    result = await asyncio.to_thread(get_container().channel_service.clone_channel, channel_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _success(result)


@channel_router.post("/test-draft")
async def test_draft_channel(dto: ChannelDTO):
    return _success(await asyncio.to_thread(get_container().channel_service.test_draft_channel, dto))


@channel_router.post("/{channel_id}/sync-models")
async def sync_channel_models(channel_id: str):
    result = await asyncio.to_thread(get_container().channel_service.sync_models, channel_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _success(result)


@channel_router.get("/{channel_id}/api-keys")
async def list_channel_api_keys(channel_id: str):
    return _success(get_container().channel_service.list_channel_api_keys(channel_id))


@channel_router.post("/{channel_id}/api-keys")
async def create_channel_api_key(channel_id: str, dto: ChannelApiKeyDTO):
    return _success(get_container().channel_service.create_channel_api_key(channel_id, dto))


@channel_router.put("/{channel_id}/api-keys/{key_id}")
async def update_channel_api_key(channel_id: str, key_id: str, dto: ChannelApiKeyDTO):
    dto.id = key_id
    return _success(get_container().channel_service.update_channel_api_key(channel_id, key_id, dto))


@channel_router.delete("/{channel_id}/api-keys/{key_id}")
async def delete_channel_api_key(channel_id: str, key_id: str):
    return _success(get_container().channel_service.delete_channel_api_key(channel_id, key_id))


# ==================== ApiKey Controller ====================

apikey_router = APIRouter(prefix="/api/v1/api-keys")


@apikey_router.get("")
async def list_api_keys():
    return _success(get_container().channel_service.list_api_keys())


@apikey_router.get("/{key_id}")
async def get_api_key(key_id: str):
    return _success(get_container().channel_service.get_api_key(key_id))


@apikey_router.get("/{key_id}/quota")
async def get_api_key_quota(key_id: str):
    key = get_container().channel_service.get_api_key(key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    limit = key.quota_limit or 0
    used = key.quota_used or 0
    return _success({"api_key_id": key.id, "quota_limit": limit or None,
                     "quota_used": used, "quota_remaining": None if not limit else max(0, limit - used)})


@apikey_router.post("")
async def create_api_key(dto: ApiKeyDTO):
    return _success(get_container().channel_service.create_api_key(dto))


@apikey_router.put("")
async def update_api_key(dto: ApiKeyDTO):
    return _success(get_container().channel_service.update_api_key(dto))


@apikey_router.delete("/{key_id}")
async def delete_api_key(key_id: str):
    return _success(get_container().channel_service.delete_api_key(key_id))


# ==================== Dashboard Controller ====================

dashboard_router = APIRouter(prefix="/api/v1")


software_router = APIRouter(prefix="/api/v1/software", tags=["Software"])


@software_router.get("/instances")
async def software_instances():
    return _success(await asyncio.to_thread(get_container().software_service.list_instances))


@software_router.post("/instances")
async def create_software_instance(dto: SoftwareInstanceInput):
    return _success(await asyncio.to_thread(get_container().software_service.create_instance, dto))


@software_router.put("/instances/{instance_id}")
async def update_software_instance(instance_id: str, dto: SoftwareInstanceInput):
    return _success(await asyncio.to_thread(get_container().software_service.update_instance, instance_id, dto))


@software_router.delete("/instances/{instance_id}")
async def delete_software_instance(instance_id: str):
    return _success(await asyncio.to_thread(get_container().software_service.delete_instance, instance_id))


@software_router.get("/tools")
async def software_tools(instance_id: str | None = None):
    return _success(await asyncio.to_thread(get_container().software_service.list_tools, instance_id))


@software_router.post("/tools")
async def create_software_tool(dto: SoftwareToolInput):
    return _success(await asyncio.to_thread(get_container().software_service.create_tool, dto))


@software_router.put("/tools/{tool_id}/enabled")
async def set_software_tool_enabled(tool_id: str, enabled: bool = True):
    return _success(await asyncio.to_thread(get_container().software_service.set_tool_enabled, tool_id, enabled))


@software_router.delete("/tools/{tool_id}")
async def delete_software_tool(tool_id: str):
    return _success(await asyncio.to_thread(get_container().software_service.delete_tool, tool_id))


@software_router.post("/tools/{tool_id}/invoke")
async def invoke_software_tool(tool_id: str, dto: SoftwareInvokeInput, request: Request):
    context = getattr(request.state, "auth_context", None)
    return _success(await asyncio.to_thread(get_container().software_service.invoke, tool_id, dto.arguments, context, dto.approved))


@software_router.get("/calls")
async def software_calls(limit: int = 100):
    return _success(await asyncio.to_thread(get_container().software_repo.list_calls, limit))


@dashboard_router.get("/dashboard")
async def dashboard():
    return _success(get_container().dashboard_service.dashboard())


@dashboard_router.get("/stats/models")
async def stats_models():
    return _success(await asyncio.to_thread(get_container().dashboard_service.model_stats))


@dashboard_router.get("/stats/token-trend")
async def stats_token_trend(days: int = 30):
    return _success(await asyncio.to_thread(get_container().dashboard_service.token_trend, days))


@dashboard_router.get("/stats/daily-tokens")
async def stats_daily_tokens(days: int = 30):
    return _success(await asyncio.to_thread(get_container().dashboard_service.token_trend, days))


@dashboard_router.get("/stats/route-flow")
async def stats_route_flow():
    return _success(await asyncio.to_thread(get_container().dashboard_service.route_flow))


@dashboard_router.post("/stats/clear")
async def stats_clear():
    return _success(await asyncio.to_thread(get_container().dashboard_service.clear_stats))


@dashboard_router.get("/logs")
async def logs(api_key_id: str | None = None, channel_id: str | None = None,
               model: str | None = None, risk_level: str | None = None,
               start_time: str | None = None, end_time: str | None = None,
               keyword: str | None = None, page: int = 1, size: int = 20,
               limit: int | None = None):
    return _success(get_container().dashboard_service.logs(
        api_key_id, channel_id, model, risk_level, start_time, end_time, keyword, page, size, limit))


@dashboard_router.get("/logs/filter-options")
async def log_filter_options():
    return _success(await asyncio.to_thread(get_container().dashboard_service.filter_options))


@dashboard_router.get("/logs/{log_id}")
async def get_log(log_id: str):
    return _success(get_container().dashboard_service.get_log(log_id))


@dashboard_router.get("/logs/{log_id}/attempts")
async def log_attempts(log_id: str):
    return _success(await asyncio.to_thread(get_container().dashboard_service.attempts, log_id))


@dashboard_router.delete("/logs/{log_id}")
async def delete_log(log_id: str):
    return _success(get_container().dashboard_service.delete_log(log_id))


@dashboard_router.delete("/logs")
async def delete_all_logs():
    return _success(get_container().dashboard_service.delete_all_logs())


@dashboard_router.delete("/logs/before")
async def delete_logs_before(cutoff: str):
    return _success(await asyncio.to_thread(get_container().dashboard_service.delete_before, cutoff))


@dashboard_router.delete("/logs/by-channel/{channel_id}")
async def delete_logs_by_channel(channel_id: str):
    return _success(await asyncio.to_thread(get_container().dashboard_service.delete_by_channel, channel_id))


# ==================== KB Controller ====================

kb_router = APIRouter(prefix="/api/v1/kb", dependencies=[Depends(require_kb_access)])


@kb_router.post("")
async def create_kb(dto: CreateKbDTO):
    return _success(get_container().kb_service.create_kb(dto))


@kb_router.get("")
async def list_kbs(request: Request):
    rows = await asyncio.to_thread(get_container().kb_service.list_kbs)
    context = getattr(request.state, "auth_context", None)
    if not context or not context.is_admin:
        allowed = await asyncio.to_thread(get_container().access_service.allowed_resources, context, "kb")
        rows = [row for row in rows if "*" in allowed or row.id in allowed]
    return _success(rows)


@kb_router.get("/{kb_id}")
async def get_kb(kb_id: str):
    return _success(get_container().kb_service.get_kb(kb_id))


@kb_router.put("/{kb_id}")
async def update_kb(kb_id: str, dto: KbKnowledgeBaseDTO):
    return _success(get_container().kb_service.update_kb(kb_id, dto))


@kb_router.delete("/{kb_id}")
async def delete_kb(kb_id: str):
    return _success(get_container().kb_service.delete_kb(kb_id))


@kb_router.post("/{kb_id}/documents")
async def upload_doc(kb_id: str, dto: UploadDocDTO):
    return _success(get_container().kb_service.upload_doc(kb_id, dto))


@kb_router.post("/{kb_id}/documents/upload")
async def upload_doc_multipart(kb_id: str, request: Request):
    from app.domain.multipart import multipart_fields, multipart_files

    payload = await request.body()
    content_type = request.headers.get("content-type", "")
    fields = multipart_fields(content_type, payload)
    files = multipart_files(content_type, payload)
    file_entry = next(iter(files.values()), None)
    if file_entry is None:
        raise HTTPException(status_code=422, detail="file is required")
    filename, _media_type, content = file_entry
    dto = UploadDocDTO(
        filename=filename,
        content=base64.b64encode(content).decode("ascii"),
        file_type=fields.get("file_type") or filename.rsplit(".", 1)[-1],
        source_type=fields.get("source_type") or "file",
    )
    return _success(get_container().kb_service.upload_doc(kb_id, dto))


@kb_router.get("/{kb_id}/documents")
async def list_docs(kb_id: str):
    return _success(get_container().kb_service.list_docs(kb_id))


@kb_router.delete("/{kb_id}/documents/{doc_id}")
async def delete_doc(kb_id: str, doc_id: str):
    return _success(get_container().kb_service.delete_doc(kb_id, doc_id))


@kb_router.post("/{kb_id}/ask")
async def ask(kb_id: str, request: KbAskRequestDTO):
    if not request.kb_id:
        request.kb_id = kb_id
    return _success(await asyncio.to_thread(get_container().kb_service.ask, kb_id, request))


@kb_router.post("/{kb_id}/deep-research")
async def deep_research(kb_id: str, request: KbAskRequestDTO):
    if not request.kb_id:
        request.kb_id = kb_id
    return _success(await asyncio.to_thread(get_container().kb_service.deep_research, kb_id, request))


@kb_router.get("/{kb_id}/conversations")
async def get_conversations(kb_id: str):
    return _success(get_container().kb_service.get_conversations(kb_id))


@kb_router.get("/{kb_id}/tasks/{task_id}")
async def get_task(kb_id: str, task_id: str):
    return _success(get_container().kb_service.get_task(kb_id, task_id))

@kb_router.post("/{kb_id}/tasks/{task_id}/cancel")
async def cancel_task(kb_id: str, task_id: str):
    return _success(get_container().kb_service.cancel_task(kb_id, task_id))


@kb_router.get("/{kb_id}/tags")
async def get_tags(kb_id: str, limit: int | None = 10):
    return _success(get_container().kb_service.get_tags(kb_id, limit))


@kb_router.post("/{kb_id}/tags/refresh")
async def refresh_tags(kb_id: str, limit: int | None = 10):
    return _success(get_container().kb_service.refresh_tags(kb_id, limit))


# --- KB additional endpoints (aligned with Java KbController) ---

@kb_router.post("/{kb_id}/search")
async def kb_search(kb_id: str, request: KbSearchRequestDTO):
    if not request.kb_id:
        request.kb_id = kb_id
    return _success(await asyncio.to_thread(get_container().kb_service.search, kb_id, request))


@kb_router.get("/{kb_id}/stats")
async def kb_stats(kb_id: str):
    return _success(get_container().kb_service.stats(kb_id))


@kb_router.delete("/{kb_id}/conversations")
async def clear_conversations(kb_id: str):
    return _success(get_container().kb_service.clear_conversations(kb_id))


@kb_router.post("/{kb_id}/documents/{doc_id}/reindex")
async def reindex_doc(kb_id: str, doc_id: str):
    return _success(get_container().kb_service.reindex_doc(kb_id, doc_id))


@kb_router.get("/{kb_id}/documents/{doc_id}")
async def get_doc(kb_id: str, doc_id: str):
    return _success(get_container().kb_service.get_doc(kb_id, doc_id))


@kb_router.get("/{kb_id}/index")
async def get_index(kb_id: str):
    return _success(get_container().kb_service.get_index_info(kb_id))


@kb_router.post("/{kb_id}/index")
async def build_index(kb_id: str):
    return _success(get_container().kb_service.build_index(kb_id))


@kb_router.delete("/{kb_id}/index")
async def drop_index(kb_id: str):
    return _success(get_container().kb_service.drop_index(kb_id))


@kb_router.get("/{kb_id}/sources")
async def list_sources(kb_id: str):
    return _success(get_container().kb_service.list_sources(kb_id))


@kb_router.post("/{kb_id}/sources")
async def create_source(kb_id: str, body: dict):
    return _success(get_container().kb_service.create_source(kb_id, body))


@kb_router.delete("/{kb_id}/sources/{source_id}")
async def delete_source(kb_id: str, source_id: str):
    return _success(get_container().kb_service.delete_source(kb_id, source_id))


# ==================== Agent Controller ====================

agent_router = APIRouter(prefix="/api/v1/agents")


@agent_router.get("")
async def list_agents():
    return _success(get_container().agent_service.list_agents())


@agent_router.get("/{agent_id}")
async def get_agent(agent_id: str):
    return _success(get_container().agent_service.get_agent(agent_id))


@agent_router.post("")
async def create_agent(dto: AgentConfigDTO):
    return _success(get_container().agent_service.create_agent(dto))


@agent_router.put("/{agent_id}")
async def update_agent(agent_id: str, dto: AgentConfigDTO):
    dto.id = agent_id
    return _success(get_container().agent_service.update_agent(dto))


@agent_router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    return _success(get_container().agent_service.delete_agent(agent_id))


@agent_router.post("/session")
async def create_session(agent_id: str = Query(...), user_id: str = Query(...)):
    return _success(get_container().agent_service.create_session(agent_id, user_id))


@agent_router.post("/{agent_id}/chat")
async def agent_chat(agent_id: str, request: AgentChatRequestDTO):
    request.agent_id = agent_id
    return _success(await asyncio.to_thread(get_container().agent_service.chat, request))


# ==================== Security Controller ====================

security_router = APIRouter(prefix="/api/v1/security")


@security_router.get("/rules/builtin")
async def list_builtin_rules():
    return _success(get_container().security_service.list_builtin_rules())


@security_router.put("/rules/builtin/{rule_id}")
async def update_builtin_rule(rule_id: str, body: dict):
    enabled = int(body["enabled"]) if body.get("enabled") is not None else None
    severity = body.get("severity")
    return _success(get_container().security_service.update_builtin_rule(rule_id, enabled, severity))


@security_router.get("/rules/custom")
async def list_custom_rules():
    return _success(get_container().security_service.list_custom_rules())


@security_router.post("/rules/custom")
async def create_custom_rule(rule: SecurityCustomRuleDTO):
    try:
        return _success(get_container().security_service.create_custom_rule(rule))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@security_router.put("/rules/custom/{rule_id}")
async def update_custom_rule(rule_id: str, rule: SecurityCustomRuleDTO):
    try:
        return _success(get_container().security_service.update_custom_rule(rule_id, rule))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@security_router.delete("/rules/custom/{rule_id}")
async def delete_custom_rule(rule_id: str):
    return _success(get_container().security_service.delete_custom_rule(rule_id))


@security_router.get("/findings")
async def list_findings(page: int = 1, size: int = 20):
    return _success(get_container().security_service.list_findings(page, size))


@security_router.get("/findings/by-log/{log_id}")
async def get_findings_by_log_id(log_id: str):
    return _success(get_container().security_service.get_findings_by_log_id(log_id))


# ==================== MCP Controller ====================

mcp_router = APIRouter(prefix="/api/mcp")


@mcp_router.get("/info")
async def mcp_info(request: Request):
    tools = await asyncio.to_thread(get_container().mcp_service.list_tools,
                                    getattr(request.state, "auth_context", None))
    return {"name": "WaLiAPI MCP Server", "version": "1.0.0", "transport": "streamable-http",
            "endpoint": "/mcp", "protocolVersion": "2025-06-18", "stateless": True,
            "tools": [tool["name"] for tool in tools["tools"]]}


@mcp_router.post("/tools/list")
async def mcp_list_tools(request: Request):
    return await asyncio.to_thread(get_container().mcp_service.list_tools,
                                    getattr(request.state, "auth_context", None))


@mcp_router.post("/tools/call")
async def mcp_call_tool(body: dict, request: Request):
    tool_name = body.get("name")
    arguments = body.get("arguments", {})
    return await asyncio.to_thread(get_container().mcp_service.call_tool, tool_name, arguments,
                                   getattr(request.state, "auth_context", None),
                                   getattr(request.state, "request_id", None))


@dashboard_router.get("/mcp/audit")
async def mcp_audit(limit: int = 100, offset: int = 0):
    return _success(get_container().mcp_audit_repo.list(limit, offset))
