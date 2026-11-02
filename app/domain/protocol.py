"""Protocol detection and API key extraction."""
import json

from app.types.enums import ProtocolFormat


class ProtocolDetector:
    @staticmethod
    def detect_endpoint(headers: dict, body: str, endpoint: str = "") -> str:
        endpoint = str(endpoint).rstrip("/")
        protocols = {"/v1/completions": "completions", "/v1/responses": "responses",
                     "/v1/messages": "anthropic", "/v1/embeddings": "openai",
                     "/v1/audio/transcriptions": "openai", "/v1/audio/speech": "openai",
                     "/v1/images/generations": "openai"}
        if endpoint in protocols:
            return protocols[endpoint]
        return ProtocolDetector.detect(headers, body)

    @staticmethod
    def detect(headers: dict, body: str) -> str:
        if headers and "anthropic-version" in headers:
            return ProtocolFormat.ANTHROPIC.value
        if headers and "x-api-key" in headers and "authorization" not in headers:
            return ProtocolFormat.ANTHROPIC.value
        try:
            j = json.loads(body)
            if "input" in j and "messages" not in j:
                return ProtocolFormat.RESPONSES.value
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return ProtocolFormat.OPENAI.value

    @staticmethod
    def extract_api_key(headers: dict) -> str | None:
        if not headers:
            return None
        auth = headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            key = auth[7:].strip()
            if key:
                return key
        api_key = headers.get("x-api-key")
        if api_key and api_key.strip():
            return api_key.strip()
        return None
