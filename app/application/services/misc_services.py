"""Security, Agent, and Proxy application services."""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import config
from app.domain.entities import (
    AgentConfigEntity,
    ProxyRequestEntity,
    RequestLogEntity,
    SecurityCustomRuleEntity,
)
from app.domain.protocol import ProtocolDetector
from app.types.auth import AuthContext
from app.types.models import (
    AgentChatRequestDTO,
    AgentChatResponseDTO,
    AgentConfigDTO,
    SecurityBuiltinRuleDTO,
    SecurityCustomRuleDTO,
    SecurityFindingDTO,
)

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(UTC).isoformat().replace("T", " ")[:19]


class SecurityService:
    def __init__(self, security_repository):
        self.repo = security_repository

    def list_builtin_rules(self):
        return [self._to_builtin_dto(e) for e in self.repo.get_all_builtin_rules()]

    def update_builtin_rule(self, rule_id, enabled, severity):
        return self.repo.update_builtin_rule(rule_id, enabled, severity)

    def list_custom_rules(self):
        return [self._to_custom_dto(e) for e in self.repo.get_all_custom_rules()]

    def create_custom_rule(self, dto: SecurityCustomRuleDTO):
        self._validate_rule(dto)
        entity = self._to_custom_entity(dto)
        created = self.repo.create_custom_rule(entity)
        return self._to_custom_dto(created)

    def update_custom_rule(self, rule_id, dto: SecurityCustomRuleDTO):
        self._validate_rule(dto)
        entity = self._to_custom_entity(dto)
        entity.id = rule_id
        return self.repo.update_custom_rule(entity)

    @staticmethod
    def _validate_rule(dto: SecurityCustomRuleDTO) -> None:
        import re
        if not dto.pattern or len(dto.pattern) > 4096:
            raise ValueError("Security rule pattern must be between 1 and 4096 characters")
        if dto.action and dto.action.lower() not in {"allow", "warn", "sanitize", "redact", "block"}:
            raise ValueError("Security rule action must be allow, warn, sanitize, redact, or block")
        # Reject the most common catastrophic-backtracking shapes when the
        # optional timeout-capable regex package is unavailable.
        if re.search(r"\([^)]*[+*][^)]*\)[+*]", dto.pattern):
            raise ValueError("Security rule pattern contains nested quantifiers")
        try:
            re.compile(dto.pattern)
        except re.error as exc:
            raise ValueError("Invalid security rule pattern") from exc

    def delete_custom_rule(self, rule_id):
        return self.repo.delete_custom_rule(rule_id)

    def list_findings(self, page, size):
        offset = (page - 1) * size
        return [self._to_finding_dto(e) for e in self.repo.get_all_findings(offset, size)]

    def get_findings_by_log_id(self, log_id):
        return [self._to_finding_dto(e) for e in self.repo.get_findings_by_log_id(log_id)]

    def _to_builtin_dto(self, e):
        return SecurityBuiltinRuleDTO(id=e.id, category=e.category, rule_id=e.rule_id, name=e.name,
                                      description=e.description, severity=e.severity, pattern=e.pattern,
                                      action=e.action, enabled=e.enabled, created_at=e.created_at, updated_at=e.updated_at)

    def _to_custom_dto(self, e):
        return SecurityCustomRuleDTO(id=e.id, category=e.category, name=e.name, description=e.description,
                                     severity=e.severity, pattern=e.pattern, action=e.action, enabled=e.enabled,
                                     created_at=e.created_at, updated_at=e.updated_at)

    def _to_custom_entity(self, dto):
        return SecurityCustomRuleEntity(id=dto.id, category=dto.category, name=dto.name, description=dto.description,
                                        severity=dto.severity, pattern=dto.pattern, action=dto.action, enabled=dto.enabled,
                                        created_at=dto.created_at, updated_at=dto.updated_at)

    def _to_finding_dto(self, e):
        return SecurityFindingDTO(id=e.id, log_id=e.log_id, phase=e.phase, category=e.category, rule_id=e.rule_id,
                                  severity=e.severity, title=e.title, description=e.description, location=e.location,
                                  evidence_masked=e.evidence_masked, evidence_hash=e.evidence_hash, action=e.action,
                                  created_at=e.created_at)


class AgentService:
    def __init__(self, agent_repository, chat_service):
        self.repo = agent_repository
        self.chat_service = chat_service

    def list_agents(self):
        return [self._to_dto(e) for e in self.repo.get_all_agents()]

    def get_agent(self, agent_id):
        return self._to_dto(self.repo.get_agent_by_id(agent_id))

    def create_agent(self, dto: AgentConfigDTO):
        entity = self._to_entity(dto)
        if not entity.id:
            entity.id = str(uuid.uuid4())
        if not entity.agent_id:
            entity.agent_id = str(uuid.uuid4())
        created = self.repo.create_agent(entity)
        return self._to_dto(created)

    def update_agent(self, dto: AgentConfigDTO):
        return self.repo.update_agent(self._to_entity(dto))

    def delete_agent(self, agent_id):
        return self.repo.delete_agent(agent_id)

    def create_session(self, agent_id, user_id):
        return self.chat_service.create_session(agent_id, user_id)

    def chat(self, request: AgentChatRequestDTO):
        user_id = request.user_id or "web"
        session_id = request.session_id
        if not session_id:
            session_id = self.chat_service.create_session(request.agent_id, user_id)
        response = self.chat_service.handle_message(request.agent_id, session_id, user_id, request.message)
        return AgentChatResponseDTO(session_id=session_id, response=response, author=request.agent_id)

    def _to_dto(self, entity):
        if not entity:
            return None
        return AgentConfigDTO(
            id=entity.id, agent_id=entity.agent_id, agent_name=entity.agent_name,
            agent_desc=entity.agent_desc, app_name=entity.app_name,
            config_json=entity.config_json, status=entity.status,
            created_at=entity.created_at, updated_at=entity.updated_at,
        )

    def _to_entity(self, dto):
        return AgentConfigEntity(
            id=dto.id, agent_id=dto.agent_id, agent_name=dto.agent_name,
            agent_desc=dto.agent_desc, app_name=dto.app_name,
            config_json=dto.config_json, status=dto.status,
            created_at=dto.created_at, updated_at=dto.updated_at,
        )


@dataclass(frozen=True)
class RawProxyResponse:
    content: bytes
    media_type: str | None = None
    headers: dict[str, str] | None = None


class ProxyService:
    """Application service for proxying requests (sync + stream) with security scanning and logging."""

    def __init__(self, gateway_service, security_scanner, security_settings, log_repository, security_repository=None, quota_repository=None, channel_repository=None):
        self.gateway = gateway_service
        self.scanner = security_scanner
        self.settings = security_settings
        self.log_repo = log_repository
        self.security_repo = security_repository
        self.quota_repo = quota_repository
        self.channel_repo = channel_repository

    def _estimate_tokens(self, body_json: dict) -> int:
        text = json.dumps(body_json, ensure_ascii=False)
        return max(1, len(text) // 4, config.api_key_quota_reserve)

    def _auth_context(self, headers: dict, auth_context: AuthContext | None = None):
        return auth_context or getattr(headers, "auth_context", None)

    def _scan(self, body: str, phase: str):
        custom = self.security_repo.get_all_custom_rules() if self.security_repo else []
        builtin = self.security_repo.get_all_builtin_rules() if self.security_repo else []
        return self.scanner.scan(body, phase, self.settings, custom, builtin)

    def forward(self, body: str | bytes, headers: dict, client_ip: str | None = None, auth_context: AuthContext | None = None, endpoint: str = "/v1/chat/completions", request_id: str | None = None, content_type: str | None = None):
        start = time.time()
        request_id = request_id or str(uuid.uuid4()).replace("-", "")
        is_multipart = isinstance(body, (bytes, bytearray)) and (content_type or "").lower().startswith("multipart/")
        raw_body = body if is_multipart and isinstance(body, bytes) else None
        if is_multipart:
            from app.domain.multipart import multipart_fields

            fields = multipart_fields(content_type, raw_body or b"")
            body = json.dumps(fields, ensure_ascii=False)
        body_text = body if isinstance(body, str) else body.decode("utf-8", "replace")
        protocol = ProtocolDetector.detect_endpoint(headers, body_text, endpoint)
        try:
            body_json = json.loads(body_text)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return 400, {"error": {"message": "Invalid JSON body", "type": "invalid_request_error", "code": "invalid_json"}}
        if protocol == "responses":
            from app.domain.responses_converter import ResponsesConverter
            converted = ResponsesConverter.responses_to_openai(body_text)
            body_json, body_text = json.loads(converted), converted
        elif protocol == "completions":
            from app.domain.completion_converter import CompletionConverter
            converted = CompletionConverter.completions_to_chat(body_text)
            body_json, body_text = json.loads(converted), converted
        model = body_json.get("model")
        if not model:
            return 400, {"error": {"message": "Missing 'model' field", "type": "invalid_request_error", "code": "missing_model"}}
        context = auth_context
        if context and context.is_api_key and context.allowed_models and model not in context.allowed_models:
            return 403, {"error": {"message": "Model is not allowed for this API key", "type": "permission_error", "code": "model_forbidden"}}
        if (context and context.is_api_key and context.allowed_channels
                and hasattr(self.gateway, "_candidates")
                and not self.gateway._candidates(model, set(), context.allowed_channels)):
            return 403, {"error": {"message": "Channel is not allowed for this API key", "type": "permission_error", "code": "channel_forbidden"}}
        scan_result = None
        if self.settings.enabled:
            try:
                scan_result = self._scan(body_text, "request")
            except Exception:
                if self.settings.fail_closed:
                    return 503, {"error": {"message": "Security scan unavailable", "type": "security_error", "code": "security_scan_failed"}}
                logger.exception("Request security scan failed")
            if scan_result and scan_result.blocked:
                log_id = str(uuid.uuid4()).replace("-", "")
                self._record_log(self._build_log(log_id, None, model, protocol, bool(body_json.get("stream")), 403, scan_result, client_ip, body_text, None, "Request blocked by security policy", request_id=request_id, endpoint=endpoint))
                return 403, {"error": {"message": "Request blocked by security policy", "type": "security_error", "code": "security_blocked"}}
            if scan_result and scan_result.sanitized and getattr(scan_result, "sanitized_body", None):
                body_text = scan_result.sanitized_body
                body_json = json.loads(body_text)
        reservation_id = None
        if context and context.is_api_key and self.quota_repo:
            reservation_id = self.quota_repo.reserve(context.principal_id, request_id, self._estimate_tokens(body_json))
            if not reservation_id:
                return 429, {"error": {"message": "API key quota exceeded", "type": "quota_error", "code": "quota_exceeded"}}
        upstream_endpoint = "/v1/chat/completions" if protocol in {"responses", "anthropic", "completions"} else endpoint
        proxy_request = ProxyRequestEntity(model=model, body=body_json, stream=bool(body_json.get("stream")), api_key=None, protocol_type=protocol, headers=headers, allowed_channels=context.allowed_channels if context else frozenset(), endpoint=upstream_endpoint, raw_body=raw_body, content_type=content_type)
        attempts = []
        try:
            if hasattr(self.gateway, "forward_with_attempts"):
                def record_attempt(attempt):
                    try:
                        if hasattr(self.log_repo, "insert_attempt"):
                            self.log_repo.insert_attempt(request_id, attempt)
                    except Exception:
                        logger.warning("Failed to record gateway attempt", exc_info=True)
                proxy_response, attempt_records = asyncio.run(
                    self.gateway.forward_with_attempts(proxy_request, on_attempt=record_attempt)
                )
                attempts = attempt_records
            else:
                proxy_response = asyncio.run(self.gateway.forward(proxy_request))
                attempts = [object()]
            if reservation_id:
                try:
                    if proxy_response.success:
                        actual_tokens = proxy_response.total_tokens or self._estimate_tokens(body_json)
                        self.quota_repo.settle(reservation_id, actual_tokens)
                    else:
                        self.quota_repo.release(reservation_id)
                except Exception:
                    logger.exception("Failed to finalize quota reservation")
        except Exception:
            if reservation_id:
                try:
                    self.quota_repo.release(reservation_id)
                except Exception:
                    logger.exception("Failed to release quota reservation after gateway error")
            raise
        if self.settings.enabled and self.settings.scan_response and proxy_response.body:
            try:
                response_scan = self._scan(proxy_response.body, "response")
                if response_scan.blocked and self.settings.fail_closed:
                    proxy_response.success = False
                    proxy_response.status_code = 502
                    proxy_response.error_message = "Response blocked by security policy"
                if scan_result is None:
                    scan_result = response_scan
                else:
                    scan_result.findings.extend(response_scan.findings)
            except Exception:  # noqa: BLE001 - response scanning is fail-closed when configured
                if self.settings.fail_closed:
                    proxy_response.success = False
                    proxy_response.status_code = 502
                    proxy_response.error_message = "Response security scan failed"
        log_id = str(uuid.uuid4()).replace("-", "")
        self._record_log(self._build_log(log_id, context.principal_id if context and context.is_api_key else None, model, protocol, proxy_request.stream, proxy_response.status_code or 502, scan_result, client_ip, body_text, proxy_response.body if proxy_response.success else None, proxy_response.error_message if not proxy_response.success else None, channel_id=proxy_response.channel_id, channel_name=proxy_response.channel_name, upstream_model=proxy_response.upstream_model, prompt_tokens=proxy_response.prompt_tokens, completion_tokens=proxy_response.completion_tokens, total_tokens=proxy_response.total_tokens, duration_ms=int((time.time()-start)*1000), request_id=request_id, endpoint=endpoint, attempt_count=len(attempts), final_attempt=len(attempts), api_key_name=context.principal_name if context and context.is_api_key else None))
        if proxy_response.success:
            if proxy_response.raw_body is not None and (
                endpoint.endswith(("/audio/speech", "/images/generations"))
                or not (proxy_response.content_type or "").lower().startswith(("application/json", "text/json"))
            ):
                return proxy_response.status_code, RawProxyResponse(
                    content=proxy_response.raw_body,
                    media_type=proxy_response.content_type,
                    headers=proxy_response.response_headers,
                )
            result = json.loads(proxy_response.body) if proxy_response.body else {}
            if protocol == "anthropic":
                from app.domain.anthropic_converter import AnthropicConverter
                result = json.loads(AnthropicConverter.chat_to_messages(proxy_response.body, model))
            if protocol == "completions":
                from app.domain.completion_converter import CompletionConverter
                result = json.loads(CompletionConverter.chat_to_completions(proxy_response.body, model))
            if protocol == "responses":
                from app.domain.responses_converter import ResponsesConverter
                result = json.loads(ResponsesConverter.openai_to_responses(proxy_response.body, model))
            return proxy_response.status_code, result
        return proxy_response.status_code or 502, {"error": {"message": proxy_response.error_message or "upstream_error", "type": "upstream_error", "code": "upstream_error"}}

    async def forward_stream_async(self, body: str, headers: dict, client_ip: str | None = None, auth_context: AuthContext | None = None, endpoint: str = "/v1/chat/completions", request_id: str | None = None):
        request_id = request_id or str(uuid.uuid4()).replace("-", "")
        protocol = ProtocolDetector.detect_endpoint(headers, body, endpoint)
        try:
            body_json = json.loads(body)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            yield 'data: {"error":{"message":"Invalid JSON body","type":"invalid_request_error"}}\n\n'; return
        if protocol == "responses":
            from app.domain.responses_converter import ResponsesConverter
            try:
                converted = ResponsesConverter.responses_to_openai(body)
                body_json, body = json.loads(converted), converted
            except (ValueError, TypeError, json.JSONDecodeError):
                yield 'data: {"error":{"message":"Invalid Responses request","type":"invalid_request_error"}}\n\n'; return
        elif protocol == "completions":
            from app.domain.completion_converter import CompletionConverter
            try:
                converted = CompletionConverter.completions_to_chat(body)
                body_json, body = json.loads(converted), converted
            except (ValueError, TypeError, json.JSONDecodeError):
                yield 'data: {"error":{"message":"Invalid Completions request","type":"invalid_request_error"}}\n\n'; return
        model = body_json.get("model")
        if not model:
            yield 'data: {"error":{"message":"Missing model field","type":"invalid_request_error"}}\n\n'; return
        context = auth_context
        if context and context.is_api_key and context.allowed_models and model not in context.allowed_models:
            yield 'data: {"error":{"message":"Model is not allowed for this API key","type":"permission_error","code":"model_forbidden"}}\n\n'; return
        if context and context.is_api_key and context.allowed_channels and hasattr(self.gateway, "_candidates") and not self.gateway._candidates(model, set(), context.allowed_channels):
            yield 'data: {"error":{"message":"Channel is not allowed for this API key","type":"permission_error","code":"channel_forbidden"}}\n\n'; return
        scan_result = None
        if self.settings.enabled:
            try:
                scan_result = self._scan(body, "request")
            except Exception:
                if self.settings.fail_closed:
                    yield 'data: {"error":{"message":"Security scan unavailable","type":"security_error","code":"security_scan_failed"}}\n\n'; return
                logger.exception("Streaming request security scan failed")
            if scan_result and scan_result.blocked:
                yield 'data: {"error":{"message":"Request blocked by security policy","type":"security_error","code":"security_blocked"}}\n\n'; return
            if scan_result and scan_result.sanitized and scan_result.sanitized_body:
                body = scan_result.sanitized_body
                body_json = json.loads(body)
        reservation_id = None
        if context and context.is_api_key and self.quota_repo:
            reservation_id = self.quota_repo.reserve(context.principal_id, request_id, self._estimate_tokens(body_json))
            if not reservation_id:
                yield 'data: {"error":{"message":"API key quota exceeded","type":"quota_error","code":"quota_exceeded"}}\n\n'; return
        chunks=[]; status="completed"; total_tokens=0; done_seen = False; attempt_records = []
        stream = None; event_name = None; data_lines: list[str] = []
        started = time.time()
        async def flush_event():
            nonlocal event_name, data_lines, done_seen, total_tokens
            if not data_lines and not event_name:
                return
            payload = "\n".join(data_lines)
            if payload == "[DONE]":
                done_seen = True
                yield "data: [DONE]\n\n"
            else:
                if event_name:
                    yield f"event: {event_name}\n"
                for line in data_lines or [""]:
                    yield f"data: {line}\n"
                yield "\n"
                chunks.append(payload)
                try:
                    usage = json.loads(payload).get("usage") or {}
                    total_tokens = max(total_tokens, int(usage.get("total_tokens", 0) or 0))
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass
            event_name = None; data_lines = []
        try:
            upstream_endpoint = "/v1/chat/completions" if protocol in {"responses", "anthropic", "completions"} else endpoint
            request = ProxyRequestEntity(model=model, body=body_json, stream=True, protocol_type=protocol, headers=headers, allowed_channels=context.allowed_channels if context else frozenset(), endpoint=upstream_endpoint)
            def record_attempt(attempt):
                attempt_records.append(attempt)
                try:
                    if hasattr(self.log_repo, "insert_attempt"):
                        self.log_repo.insert_attempt(request_id, attempt)
                except Exception:
                    logger.warning("Failed to record streaming gateway attempt", exc_info=True)

            try:
                stream = self.gateway.stream(request, on_attempt=record_attempt)
            except TypeError:
                # Preserve compatibility with simple gateway adapters that predate
                # the optional attempt callback.
                stream = self.gateway.stream(request)
            async for raw_line in stream:
                line = raw_line.rstrip("\r")
                if line == "":
                    async for output in flush_event():
                        yield output
                    if done_seen:
                        break
                elif line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line.startswith(":"):
                    yield line + "\n\n"
            if data_lines or event_name:
                async for output in flush_event():
                    yield output
            if not done_seen:
                yield "data: [DONE]\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            status="client_disconnect"
            raise
        except Exception:  # noqa: BLE001 - convert upstream failures to a safe SSE error
            status="error"
            safe=json.dumps({"error":{"message":"upstream stream failed","type":"upstream_error","code":"upstream_error"}})
            yield f"data: {safe}\n\n"
        finally:
            if stream is not None and hasattr(stream, "aclose"):
                try:
                    await stream.aclose()
                except Exception:
                    logger.debug("Failed to close upstream stream", exc_info=True)
            if reservation_id:
                try:
                    if status == "completed":
                        self.quota_repo.settle(reservation_id, total_tokens or self._estimate_tokens(body_json))
                    else:
                        self.quota_repo.release(reservation_id)
                except Exception:
                    logger.exception("Failed to finalize streaming quota reservation")
            log_id=str(uuid.uuid4()).replace("-","")
            self._record_log(self._build_log(log_id, context.principal_id if context and context.is_api_key else None, model, protocol, True, 200 if status=="completed" else 502, scan_result, client_ip, body, "\n".join(chunks), None, request_id=request_id, endpoint=endpoint, stream_status=status, usage_source="upstream" if total_tokens else "estimated", duration_ms=int((time.time()-started)*1000), api_key_name=context.principal_name if context and context.is_api_key else None, client_disconnect=status == "client_disconnect", attempt_count=len(attempt_records), final_attempt=len(attempt_records)))

    def forward_stream(self, body: str, headers: dict, client_ip: str | None = None, auth_context: AuthContext | None = None, endpoint: str = "/v1/chat/completions", request_id: str | None = None):
        """Legacy synchronous adapter for callers outside an ASGI request."""
        async def collect():
            async for item in self.forward_stream_async(body, headers, client_ip, auth_context, endpoint, request_id):
                yield item
        loop = asyncio.new_event_loop()
        try:
            iterator = collect().__aiter__()
            while True:
                try:
                    yield loop.run_until_complete(iterator.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _build_log(self, log_id, api_key, model, protocol, is_stream, status_code, scan_result,
                   client_ip, request_body, response_choices, error_message,
                   channel_id=None, channel_name=None, upstream_model=None,
                   prompt_tokens=0, completion_tokens=0, total_tokens=0, duration_ms=0,
                   request_id=None, endpoint=None, attempt_count=1, final_attempt=1,
                   stream_status=None, usage_source=None, client_disconnect=False, truncated=False, api_key_name=None):
        risk_level = "Clean"
        risk_score = 0
        risk_summary = None
        security_action = "Allow"
        sanitized = False
        blocked_reason = None
        if scan_result:
            risk_level = scan_result.risk_level or "Clean"
            risk_score = scan_result.risk_score
            risk_summary = scan_result.summary
            if scan_result.blocked:
                security_action = "Block"
                blocked_reason = scan_result.blocked_reason
            elif scan_result.sanitized:
                security_action = "Sanitize"
                sanitized = True
        body_limit = getattr(config.gateway, "max_response_log_bytes", 65536)
        truncated_body = request_body[:body_limit] if request_body else None
        truncated_choices = response_choices[:body_limit] if response_choices else None
        if response_choices and len(response_choices) > body_limit:
            truncated = True
        entry = RequestLogEntity(
            id=log_id, api_key_id=api_key, api_key_name=api_key_name, channel_id=channel_id, channel_name=channel_name,
            model=model, upstream_model=upstream_model, mode="chat", protocol_type=protocol,
            stream=is_stream, status_code=status_code, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, total_tokens=total_tokens, duration_ms=duration_ms,
            risk_level=risk_level, risk_score=risk_score, risk_summary=risk_summary,
            security_action=security_action, sanitized=sanitized, blocked_reason=blocked_reason,
            client_ip=client_ip, error_message=error_message, request_body=truncated_body,
            response_choices=truncated_choices, trace_id=log_id, created_at=_now(),
            request_id=request_id, endpoint=endpoint, attempt_count=attempt_count,
            final_attempt=final_attempt, stream_status=stream_status, usage_source=usage_source,
            client_disconnect=client_disconnect, truncated=truncated,
        )
        if scan_result and scan_result.findings:
            entry._security_findings = scan_result.findings
        return entry

    def _record_log(self, entry):
        try:
            self.log_repo.insert_log(entry)
            if self.security_repo:
                findings = getattr(entry, "_security_findings", None)
                if findings:
                    for finding in findings:
                        finding.log_id = entry.id
                    self.security_repo.save_findings(findings)
        except Exception as e:  # noqa: BLE001 - logging must not break the response path
            logger.warning(f"Failed to insert request log: {e}")


class McpService:
    """MCP service for tool listing and calling."""

    def __init__(self, kb_service, access_service=None, wiki_service=None, audit_repository=None, software_service=None):
        self.kb_service = kb_service
        self.access = access_service
        self.wiki_service = wiki_service
        self.audit = audit_repository
        self.software_service = software_service

    def list_tools(self, auth_context=None):
        from app.types.mcp import TOOL_ARGUMENTS
        descriptions = {
            "create_knowledge_base": "Create a knowledge base.",
            "update_knowledge_base": "Update a knowledge base.",
            "delete_knowledge_base": "Delete a knowledge base.",
            "ask_knowledge_base": "Ask a question to a knowledge base and get an answer.",
            "search_knowledge_base": "Search a knowledge base for relevant chunks.",
            "list_knowledge_bases": "List all available knowledge bases.",
            "upload_knowledge_document": "Upload a document to a knowledge base.",
            "get_knowledge_document": "Read one knowledge base document.",
            "list_knowledge_documents": "List documents in a knowledge base.",
            "delete_knowledge_document": "Delete a knowledge base document.",
            "reindex_knowledge_document": "Rebuild one knowledge base document index.",
            "build_knowledge_index": "Build a knowledge base index.",
            "drop_knowledge_index": "Delete a knowledge base index.",
            "list_knowledge_sources": "List knowledge base import sources.",
            "create_knowledge_source": "Create a knowledge base import source.",
            "delete_knowledge_source": "Delete a knowledge base import source.",
            "list_wiki_projects": "List Wiki projects available to the caller.",
            "list_wiki_pages": "Search pages in a Wiki project.",
            "get_wiki_page": "Read one Wiki page.",
            "get_wiki_tags": "List Wiki page tags.",
            "get_wiki_graph": "Return Wiki page relationships.",
            "ask_wiki": "Ask a question against a Wiki project.",
            "invoke_software_tool": "Invoke an approved software tool.",
        }
        tools = [
            {"name": name, "description": descriptions[name],
             "inputSchema": schema.model_json_schema()}
            for name, schema in TOOL_ARGUMENTS.items()
            if self.wiki_service is not None or not name.startswith(("list_wiki", "get_wiki", "ask_wiki"))
            if self.software_service is not None or name != "invoke_software_tool"
            if self.access is None or self.access.can(auth_context, "mcp_tool", name, "execute")
        ]
        if self.software_service is not None:
            for tool in self.software_service.list_tools():
                if tool.get("enabled", 1) == 0:
                    continue
                tools.append({
                    "name": f"software.{tool['id']}.{tool['name']}",
                    "description": tool.get("description") or "Software connector tool",
                    "inputSchema": tool.get("input_schema") or {"type": "object"},
                })
        return {"tools": tools}

    @staticmethod
    def validate_arguments(tool_name, arguments):
        from pydantic import ValidationError

        from app.types.mcp import TOOL_ARGUMENTS
        if isinstance(tool_name, str) and tool_name.startswith("software."):
            if not isinstance(arguments, dict):
                raise ValueError("Invalid tool arguments")
            parts = tool_name.split(".", 2)
            if len(parts) != 3 or not parts[1] or not parts[2]:
                raise ValueError("Unknown tool")
            return {"tool_id": parts[1], "arguments": arguments, "approved": False}
        if not isinstance(tool_name, str) or tool_name not in TOOL_ARGUMENTS:
            raise ValueError("Unknown tool")
        try:
            return TOOL_ARGUMENTS[tool_name].model_validate(arguments).model_dump()
        except ValidationError as exc:
            raise ValueError("Invalid tool arguments") from exc

    def call_tool(self, tool_name, arguments, auth_context=None, request_id=None):
        started = time.monotonic()
        try:
            arguments = self.validate_arguments(tool_name, arguments)
        except ValueError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        if self.access is not None:
            if not self.access.can(auth_context, "mcp_tool", tool_name, "execute"):
                return {"content": [{"type": "text", "text": "Tool access denied"}], "isError": True}
            if tool_name.startswith("software.") and not self.access.can(auth_context, "software", arguments["tool_id"], "execute"):
                return {"content": [{"type": "text", "text": "Software tool access denied"}], "isError": True}
            if "kb_id" in arguments:
                action = self._tool_resource_action(tool_name)
                if not self.access.can(auth_context, "kb", arguments["kb_id"], action):
                    return {"content": [{"type": "text", "text": "Knowledge base access denied"}], "isError": True}
            if "project_id" in arguments and not self.access.can(auth_context, "wiki", arguments["project_id"]):
                return {"content": [{"type": "text", "text": "Wiki access denied"}], "isError": True}
        handlers = {
            "ask_knowledge_base": lambda: self._handle_ask(arguments),
            "search_knowledge_base": lambda: self._handle_search(arguments),
            "list_knowledge_bases": lambda: self._handle_list(auth_context),
            "create_knowledge_base": lambda: self._handle_create_kb(arguments),
            "update_knowledge_base": lambda: self._handle_update_kb(arguments),
            "delete_knowledge_base": lambda: self._handle_delete_kb(arguments),
            "upload_knowledge_document": lambda: self._handle_upload_document(arguments),
            "get_knowledge_document": lambda: self._handle_get_document(arguments),
            "list_knowledge_documents": lambda: self._handle_list_documents(arguments),
            "delete_knowledge_document": lambda: self._handle_delete_document(arguments),
            "reindex_knowledge_document": lambda: self._handle_reindex_document(arguments),
            "build_knowledge_index": lambda: self._handle_build_index(arguments),
            "drop_knowledge_index": lambda: self._handle_drop_index(arguments),
            "list_knowledge_sources": lambda: self._handle_list_sources(arguments),
            "create_knowledge_source": lambda: self._handle_create_source(arguments),
            "delete_knowledge_source": lambda: self._handle_delete_source(arguments),
            "list_wiki_projects": lambda: self._handle_wiki_projects(auth_context),
            "list_wiki_pages": lambda: self._handle_wiki_pages(arguments),
            "get_wiki_page": lambda: self._handle_wiki_page(arguments),
            "get_wiki_tags": lambda: self._handle_wiki_tags(arguments),
            "get_wiki_graph": lambda: self._handle_wiki_graph(arguments),
            "ask_wiki": lambda: self._handle_wiki_ask(arguments, auth_context),
            "invoke_software_tool": lambda: self._handle_software_tool(arguments, auth_context),
        }
        try:
            if tool_name.startswith("software."):
                result = self._handle_software_tool(arguments, auth_context)
            else:
                result = handlers[tool_name]()
        except Exception as exc:  # noqa: BLE001 - tool errors are intentionally sanitized
            logger.error("MCP tool execution failed: tool=%s error_type=%s", tool_name, type(exc).__name__)
            result = {"content": [{"type": "text", "text": "Tool execution failed"}], "isError": True}
        duration_ms = int((time.monotonic() - started) * 1000)
        if self.audit is not None:
            try:
                self.audit.record(
                    request_id=request_id,
                    principal_type=getattr(auth_context, "principal_type", None),
                    principal_id=getattr(auth_context, "principal_id", None),
                    tool_name=tool_name,
                    success=not bool(result.get("isError")),
                    error_type="tool_error" if result.get("isError") else None,
                    duration_ms=duration_ms,
                )
            except Exception:
                logger.warning("Failed to persist MCP audit record", exc_info=True)
        logger.info("MCP tool executed: tool=%s is_error=%s duration_ms=%s", tool_name, bool(result.get("isError")), duration_ms, extra={
            "tool": tool_name, "is_error": bool(result.get("isError")),
            "duration_ms": duration_ms,
        })
        return result

    @staticmethod
    def _tool_resource_action(tool_name):
        if tool_name.startswith(("create_", "update_", "upload_")):
            return "write"
        if tool_name.startswith(("delete_", "drop_")):
            return "write"
        if tool_name.startswith(("reindex_", "build_")):
            return "write"
        return "read"

    def _handle_ask(self, args):
        from app.types.models import KbAskRequestDTO
        kb_id = args.get("kb_id")
        question = args.get("question")
        top_k = args.get("top_k", 5)
        search_mode = args.get("search_mode", "hybrid")
        if not kb_id or not question:
            return {"content": [{"type": "text", "text": "Error: kb_id and question are required"}], "isError": True}
        request = KbAskRequestDTO(kb_id=kb_id, question=question, top_k=top_k, search_mode=search_mode)
        answer = self.kb_service.ask(kb_id, request)
        return {"content": [{"type": "text", "text": answer.answer or "No answer generated"},
                            {"type": "text", "text": json.dumps({"sources": answer.sources}, ensure_ascii=False)}],
                "sources": answer.sources}

    def _handle_create_kb(self, args):
        from app.types.models import CreateKbDTO
        result = self.kb_service.create_kb(CreateKbDTO(**args))
        return {"content": [{"type": "text", "text": json.dumps(self._serialize_document(result), ensure_ascii=False, default=str)}], "knowledgeBase": self._serialize_document(result)}

    def _handle_update_kb(self, args):
        from app.types.models import KbKnowledgeBaseDTO
        kb_id = args["kb_id"]
        result = self.kb_service.update_kb(kb_id, KbKnowledgeBaseDTO(id=kb_id, **{key: value for key, value in args.items() if key != "kb_id"}))
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "updated": bool(result)}

    def _handle_delete_kb(self, args):
        result = self.kb_service.delete_kb(args["kb_id"])
        return {"content": [{"type": "text", "text": "Knowledge base deleted"}], "deleted": bool(result)}

    def _handle_upload_document(self, args):
        from app.types.models import UploadDocDTO
        kb_id = args["kb_id"]
        payload = {key: value for key, value in args.items() if key != "kb_id"}
        result = self.kb_service.upload_doc(kb_id, UploadDocDTO(**payload))
        return {"content": [{"type": "text", "text": json.dumps(self._serialize_document(result), ensure_ascii=False, default=str)}], "document": self._serialize_document(result)}

    def _handle_delete_document(self, args):
        result = self.kb_service.delete_doc(args["kb_id"], args["doc_id"])
        return {"content": [{"type": "text", "text": "Document deleted"}], "deleted": bool(result)}

    def _handle_build_index(self, args):
        result = self.kb_service.build_index(args["kb_id"])
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "result": result}

    def _handle_drop_index(self, args):
        result = self.kb_service.drop_index(args["kb_id"])
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "result": result}

    def _handle_list_sources(self, args):
        result = self.kb_service.list_sources(args["kb_id"])
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "sources": result}

    def _handle_create_source(self, args):
        kb_id = args["kb_id"]
        result = self.kb_service.create_source(kb_id, {key: value for key, value in args.items() if key != "kb_id"})
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "source": result}

    def _handle_delete_source(self, args):
        result = self.kb_service.delete_source(args["kb_id"], args["source_id"])
        return {"content": [{"type": "text", "text": "Source deleted"}], "deleted": bool(result)}

    def _handle_software_tool(self, args, auth_context=None):
        if self.software_service is None:
            return {"content": [{"type": "text", "text": "Software service unavailable"}], "isError": True}
        result = self.software_service.invoke(args["tool_id"], args.get("arguments", {}), auth_context, args.get("approved", False))
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "result": result}

    def _handle_search(self, args):
        from app.types.models import KbSearchRequestDTO
        kb_id = args.get("kb_id")
        query = args.get("query")
        top_k = args.get("top_k", 5)
        search_mode = args.get("search_mode", "keyword")
        if not kb_id or not query:
            return {"content": [{"type": "text", "text": "Error: kb_id and query are required"}], "isError": True}
        request = KbSearchRequestDTO(query=query, top_k=top_k, search_mode=search_mode)
        results = self.kb_service.search_kb(kb_id, request)
        content_items = [{"type": "text", "text": f"[Score: {r.score:.2f}] {r.content}"} for r in results]
        return {"content": content_items, "resultCount": len(results)}

    def _handle_list(self, auth_context=None):
        kbs = self.kb_service.list_kbs()
        if self.access is not None:
            allowed = self.access.allowed_resources(auth_context, "kb")
            kbs = [kb for kb in kbs if "*" in allowed or kb.id in allowed]
        kb_list = [{"id": kb.id, "name": kb.name, "description": kb.description, "indexStatus": kb.index_status} for kb in kbs]
        return {"content": [{"type": "text", "text": json.dumps(kb_list, ensure_ascii=False)}], "knowledgeBases": kb_list}

    def _handle_get_document(self, args):
        document = self.kb_service.get_doc(args["kb_id"], args["doc_id"])
        if not document:
            return {"content": [{"type": "text", "text": "Document not found"}], "isError": True}
        document = self._serialize_document(document)
        return {"content": [{"type": "text", "text": json.dumps(document, ensure_ascii=False, default=str)}], "document": document}

    def _handle_list_documents(self, args):
        documents = self.kb_service.list_docs(args["kb_id"])
        rows = [self._serialize_document(document) for document in documents]
        return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, default=str)}], "documents": rows}

    def _handle_reindex_document(self, args):
        result = self.kb_service.reindex_doc(args["kb_id"], args["doc_id"])
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "result": result}

    @staticmethod
    def _serialize_document(document):
        if hasattr(document, "model_dump"):
            return document.model_dump()
        if isinstance(document, dict):
            return document
        return vars(document)

    def _handle_wiki_projects(self, auth_context=None):
        if self.wiki_service is None:
            return {"content": [{"type": "text", "text": "Wiki service unavailable"}], "isError": True}
        rows = self.wiki_service.repo.list_projects()
        if self.access is not None:
            allowed = self.access.allowed_resources(auth_context, "wiki")
            rows = [row for row in rows if "*" in allowed or row["id"] in allowed]
        return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, default=str)}], "projects": rows}

    def _handle_wiki_pages(self, args):
        rows = self.wiki_service.list_pages(args["project_id"], args.get("query", ""), args.get("tag"))
        return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, default=str)}], "pages": rows}

    def _handle_wiki_page(self, args):
        page = self.wiki_service.repo.get_page(args["project_id"], args["page_id"])
        if not page:
            return {"content": [{"type": "text", "text": "Wiki page not found"}], "isError": True}
        from app.application.services.wiki_service import page_view
        page = page_view(page)
        return {"content": [{"type": "text", "text": json.dumps(page, ensure_ascii=False, default=str)}], "page": page}

    def _handle_wiki_tags(self, args):
        tags = self.wiki_service.tags(args["project_id"])
        return {"content": [{"type": "text", "text": json.dumps(tags, ensure_ascii=False)}], "tags": tags}

    def _handle_wiki_graph(self, args):
        graph = self.wiki_service.graph(args["project_id"])
        return {"content": [{"type": "text", "text": json.dumps(graph, ensure_ascii=False)}], "graph": graph}

    def _handle_wiki_ask(self, args, auth_context=None):
        from app.types.wiki import WikiAskInput
        dto = WikiAskInput(question=args["question"], model=args["model"], top_k=args["top_k"])
        result = self.wiki_service.ask(args["project_id"], dto, auth_context=auth_context)
        return {"content": [{"type": "text", "text": result.get("answer", "")}, {"type": "text", "text": json.dumps(result.get("sources", []), ensure_ascii=False)}], "answer": result}
