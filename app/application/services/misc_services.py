"""Security, Agent, and Proxy application services."""
import uuid
import json
import logging
import time
import uuid as uuid_mod
from datetime import datetime, timezone

from app.types.models import (
    AgentConfigDTO, AgentChatRequestDTO, AgentChatResponseDTO,
    SecurityBuiltinRuleDTO, SecurityCustomRuleDTO, SecurityFindingDTO,
)
from app.domain.entities import (
    AgentConfigEntity, SecurityBuiltinRuleEntity, SecurityCustomRuleEntity,
    RequestLogEntity, ProxyRequestEntity,
)
from app.domain.protocol import ProtocolDetector
from app.types.enums import RiskLevel

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("T", " ")[:19]


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
        entity = self._to_custom_entity(dto)
        created = self.repo.create_custom_rule(entity)
        return self._to_custom_dto(created)

    def update_custom_rule(self, rule_id, dto: SecurityCustomRuleDTO):
        entity = self._to_custom_entity(dto)
        entity.id = rule_id
        return self.repo.update_custom_rule(entity)

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
        self.chat = chat_service

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
        return self.chat.create_session(agent_id, user_id)

    def chat(self, request: AgentChatRequestDTO):
        user_id = request.user_id or "web"
        session_id = request.session_id
        if not session_id:
            session_id = self.chat.create_session(request.agent_id, user_id)
        response = self.chat.handle_message(request.agent_id, session_id, user_id, request.message)
        return AgentChatResponseDTO(session_id=session_id, response=response, author=request.agent_id)

    def _to_dto(self, e):
        if not e: return None
        return AgentConfigDTO(id=e.id, agent_id=e.agent_id, agent_name=e.agent_name, agent_desc=e.agent_desc,
                              app_name=e.app_name, config_json=e.config_json, status=e.status,
                              created_at=e.created_at, updated_at=e.updated_at)

    def _to_entity(self, dto):
        return AgentConfigEntity(id=dto.id, agent_id=dto.agent_id, agent_name=dto.agent_name,
                                 agent_desc=dto.agent_desc, app_name=dto.app_name, config_json=dto.config_json,
                                 status=dto.status, created_at=dto.created_at, updated_at=dto.updated_at)


class ProxyService:
    """Application service for proxying requests (sync + stream) with security scanning and logging."""

    def __init__(self, gateway_service, security_scanner, security_settings, log_repository, security_repository=None):
        self.gateway = gateway_service
        self.scanner = security_scanner
        self.settings = security_settings
        self.log_repo = log_repository
        self.security_repo = security_repository

    def forward(self, body: str, headers: dict, client_ip: str = None):
        start = time.time()
        protocol = ProtocolDetector.detect(headers, body)
        try:
            body_json = json.loads(body)
        except Exception:
            return 400, {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}}

        # Responses API protocol: convert to OpenAI Chat Completions format before forwarding
        if protocol == "responses":
            from app.domain.responses_converter import ResponsesConverter
            converted = ResponsesConverter.responses_to_openai(body)
            body_json = json.loads(converted)
            body = converted

        model = body_json.get("model")
        if not model:
            return 400, {"error": {"message": "Missing 'model' field", "type": "invalid_request_error"}}

        scan_result = None
        if self.settings.enabled:
            scan_result = self.scanner.scan(body, "request", self.settings)
            if scan_result.blocked:
                log_id = str(uuid.uuid4()).replace("-", "")
                self._record_log(self._build_log(log_id, ProtocolDetector.extract_api_key(headers), model, protocol,
                                                  body_json.get("stream", False), 403, scan_result, client_ip, body, None,
                                                  "Request blocked: " + (scan_result.blocked_reason or "")))
                return 403, {"error": {"message": "Request blocked by security policy: " + (scan_result.blocked_reason or ""), "type": "security_error"}}

        is_stream = body_json.get("stream", False)
        proxy_request = ProxyRequestEntity(
            model=model, body=body_json, stream=is_stream,
            api_key=ProtocolDetector.extract_api_key(headers), protocol_type=protocol, headers=headers,
        )
        proxy_response = self.gateway.forward(proxy_request)

        log_id = str(uuid.uuid4()).replace("-", "")
        self._record_log(self._build_log(
            log_id, ProtocolDetector.extract_api_key(headers), model, protocol, is_stream,
            proxy_response.status_code if proxy_response.success else (proxy_response.status_code or 502),
            scan_result, client_ip, body, proxy_response.body if proxy_response.success else None,
            proxy_response.error_message if not proxy_response.success else None,
            channel_id=proxy_response.channel_id, channel_name=proxy_response.channel_name,
            upstream_model=proxy_response.upstream_model, prompt_tokens=proxy_response.prompt_tokens,
            completion_tokens=proxy_response.completion_tokens, total_tokens=proxy_response.total_tokens,
            duration_ms=int((time.time() - start) * 1000),
        ))

        if proxy_response.success:
            result = json.loads(proxy_response.body) if proxy_response.body else {}
            # Convert OpenAI response back to Responses API format
            if protocol == "responses":
                from app.domain.responses_converter import ResponsesConverter
                result = json.loads(ResponsesConverter.openai_to_responses(proxy_response.body, model))
            return proxy_response.status_code, result
        else:
            status = proxy_response.status_code if proxy_response.status_code and proxy_response.status_code > 0 else 502
            return status, {"error": {"message": proxy_response.error_message or "upstream_error", "type": "upstream_error"}}

    def forward_stream(self, body: str, headers: dict, client_ip: str = None):
        """Returns a generator yielding SSE chunks."""
        start = time.time()
        protocol = ProtocolDetector.detect(headers, body)
        try:
            body_json = json.loads(body)
        except Exception:
            yield 'data: {"error":{"message":"Invalid JSON body","type":"invalid_request_error"}}\n\n'
            return

        model = body_json.get("model")
        if not model:
            yield 'data: {"error":{"message":"Missing model field","type":"invalid_request_error"}}\n\n'
            return

        scan_result = None
        if self.settings.enabled:
            scan_result = self.scanner.scan(body, "request", self.settings)
            if scan_result.blocked:
                log_id = str(uuid.uuid4()).replace("-", "")
                self._record_log(self._build_log(log_id, ProtocolDetector.extract_api_key(headers), model, protocol,
                                                  True, 403, scan_result, client_ip, body, None,
                                                  "Request blocked: " + (scan_result.blocked_reason or "")))
                yield 'data: {"error":{"message":"Request blocked by security policy: ' + (scan_result.blocked_reason or "") + '","type":"security_error"}}\n\n'
                return

        proxy_request = ProxyRequestEntity(
            model=model, body=body_json, stream=True,
            api_key=ProtocolDetector.extract_api_key(headers), protocol_type=protocol, headers=headers,
        )

        response_buffer = []
        error_occurred = []

        def on_chunk(chunk):
            response_buffer.append(chunk)

        def on_error(err):
            error_occurred.append(err)

        def on_complete():
            pass

        # Run the stream forward in a thread and yield chunks
        import queue
        import threading
        q = queue.Queue()
        done_marker = object()

        def _on_chunk(chunk):
            q.put(chunk)

        def _on_error(err):
            q.put(err)

        def _on_complete():
            q.put(done_marker)

        def _run():
            self.gateway.forward_stream(proxy_request, _on_chunk, _on_error, _on_complete)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        while True:
            item = q.get()
            if item is done_marker:
                break
            if isinstance(item, Exception):
                yield 'data: {"error":{"message":"' + str(item) + '","type":"upstream_error"}}\n\n'
                break
            yield f"data: {item}\n\n"

        yield "data: [DONE]\n\n"

        log_id = str(uuid.uuid4()).replace("-", "")
        response_text = "".join(response_buffer)[:65536] if response_buffer else None
        self._record_log(self._build_log(
            log_id, ProtocolDetector.extract_api_key(headers), model, protocol, True,
            200, scan_result, client_ip, body, response_text, None,
            duration_ms=int((time.time() - start) * 1000),
        ))

    def _build_log(self, log_id, api_key, model, protocol, is_stream, status_code, scan_result,
                   client_ip, request_body, response_choices, error_message,
                   channel_id=None, channel_name=None, upstream_model=None,
                   prompt_tokens=0, completion_tokens=0, total_tokens=0, duration_ms=0):
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
        truncated_body = request_body[:65536] if request_body else None
        truncated_choices = response_choices[:65536] if response_choices else None
        return RequestLogEntity(
            id=log_id, api_key_id=api_key, channel_id=channel_id, channel_name=channel_name,
            model=model, upstream_model=upstream_model, mode="chat", protocol_type=protocol,
            stream=is_stream, status_code=status_code, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, total_tokens=total_tokens, duration_ms=duration_ms,
            risk_level=risk_level, risk_score=risk_score, risk_summary=risk_summary,
            security_action=security_action, sanitized=sanitized, blocked_reason=blocked_reason,
            client_ip=client_ip, error_message=error_message, request_body=truncated_body,
            response_choices=truncated_choices, trace_id=log_id, created_at=_now(),
        )

    def _record_log(self, entry):
        try:
            self.log_repo.insert_log(entry)
        except Exception as e:
            logger.warning(f"Failed to insert request log: {e}")


class McpService:
    """MCP service for tool listing and calling."""

    def __init__(self, kb_service):
        self.kb_service = kb_service

    def list_tools(self):
        return {"tools": [
            {"name": "ask_knowledge_base", "description": "Ask a question to a knowledge base and get an answer.",
             "inputSchema": {"type": "object", "properties": {
                 "kb_id": {"type": "string"}, "question": {"type": "string"},
                 "top_k": {"type": "integer", "default": 5}, "search_mode": {"type": "string", "default": "hybrid"}},
                 "required": ["kb_id", "question"]}},
            {"name": "search_knowledge_base", "description": "Search a knowledge base for relevant chunks.",
             "inputSchema": {"type": "object", "properties": {
                 "kb_id": {"type": "string"}, "query": {"type": "string"},
                 "top_k": {"type": "integer", "default": 5}, "search_mode": {"type": "string", "default": "keyword"}},
                 "required": ["kb_id", "query"]}},
            {"name": "list_knowledge_bases", "description": "List all available knowledge bases.",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
        ]}

    def call_tool(self, tool_name, arguments):
        try:
            if tool_name == "ask_knowledge_base":
                return self._handle_ask(arguments)
            elif tool_name == "search_knowledge_base":
                return self._handle_search(arguments)
            elif tool_name == "list_knowledge_bases":
                return self._handle_list()
            else:
                return {"content": [{"type": "text", "text": "Unknown tool: " + tool_name}], "isError": True}
        except Exception as e:
            logger.error(f"MCP tool call failed: {tool_name}: {e}")
            return {"content": [{"type": "text", "text": "Error: " + str(e)}], "isError": True}

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
        return {"content": [{"type": "text", "text": answer.answer or "No answer generated"}], "sources": answer.sources}

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

    def _handle_list(self):
        kbs = self.kb_service.list_kbs()
        kb_list = [{"id": kb.id, "name": kb.name, "description": kb.description, "indexStatus": kb.index_status} for kb in kbs]
        return {"content": [{"type": "text", "text": f"Found {len(kbs)} knowledge base(s)"}], "knowledgeBases": kb_list}
