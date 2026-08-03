"""Agent chat service: manages sessions and routes messages through the gateway."""
import json
import uuid
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from app.domain.entities import ProxyRequestEntity

logger = logging.getLogger(__name__)

DEFAULT_CHAT_MODEL = "gemini-2.0-flash"


class AgentChatService:
    """Manages agent chat sessions and forwards messages through the gateway."""

    def __init__(self, agent_repository, channel_repository, gateway_service):
        self.agent_repository = agent_repository
        self.channel_repository = channel_repository
        self.gateway_service = gateway_service
        self._sessions = defaultdict(list)

    def create_session(self, agent_id, user_id):
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = []
        config = self.agent_repository.get_agent_by_agent_id(agent_id)
        if config and config.config_json:
            try:
                cfg = json.loads(config.config_json)
                instruction = cfg.get("instruction")
                if instruction:
                    self._sessions[session_id].append({"role": "system", "content": instruction})
            except Exception:
                pass
        logger.info(f"Created session {session_id} for agent {agent_id}")
        return session_id

    def _get_available_api_key(self):
        try:
            keys = self.channel_repository.get_all_api_keys()
            if keys:
                for key in keys:
                    if key.status == 1 and key.key:
                        return key.key
                for key in keys:
                    if key.key:
                        return key.key
        except Exception:
            pass
        return None

    def handle_message(self, agent_id, session_id, user_id, message):
        if session_id not in self._sessions:
            self.create_session(agent_id, user_id)
        messages = self._sessions[session_id]
        messages.append({"role": "user", "content": message})

        config = self.agent_repository.get_agent_by_agent_id(agent_id)
        model = DEFAULT_CHAT_MODEL
        if config and config.config_json:
            try:
                cfg = json.loads(config.config_json)
                cfg_model = cfg.get("model")
                if cfg_model:
                    model = cfg_model
            except Exception:
                pass

        body = {"model": model, "messages": messages, "stream": False}
        request = ProxyRequestEntity(model=model, body=body, stream=False, protocol_type="openai")
        response = self.gateway_service.forward(request)

        if not response.success:
            return "\u5bf9\u8bdd\u5931\u8d25: " + (response.error_message or "")
        if not response.body:
            return "\u7f51\u5173\u8fd4\u56de\u7a7a\u54cd\u5e94"

        try:
            resp_json = json.loads(response.body)
            content = resp_json["choices"][0]["message"]["content"]
            messages.append({"role": "assistant", "content": content})
            return content
        except Exception as e:
            return "\u5bf9\u8bdd\u5931\u8d25: " + str(e)

    def handle_message_stream(self, agent_id, session_id, user_id, message, on_chunk, on_error, on_complete):
        try:
            if session_id not in self._sessions:
                self.create_session(agent_id, user_id)
            messages = self._sessions[session_id]
            messages.append({"role": "user", "content": message})

            config = self.agent_repository.get_agent_by_agent_id(agent_id)
            model = DEFAULT_CHAT_MODEL
            if config and config.config_json:
                try:
                    cfg = json.loads(config.config_json)
                    cfg_model = cfg.get("model")
                    if cfg_model:
                        model = cfg_model
                except Exception:
                    pass

            body = {"model": model, "messages": messages, "stream": True}
            request = ProxyRequestEntity(model=model, body=body, stream=True, protocol_type="openai")

            full_content = []

            def _on_chunk(chunk):
                if chunk.startswith("data: "):
                    chunk = chunk[6:].strip()
                if chunk == "[DONE]":
                    return
                try:
                    chunk_json = json.loads(chunk)
                    choices = chunk_json.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if "content" in delta:
                            content = delta["content"]
                            if content:
                                full_content.append(content)
                                on_chunk(content)
                except Exception:
                    pass

            def _on_complete():
                if full_content:
                    messages.append({"role": "assistant", "content": "".join(full_content)})
                on_complete()

            self.gateway_service.forward_stream(request, _on_chunk, on_error, _on_complete)
        except Exception as e:
            on_error(e)
