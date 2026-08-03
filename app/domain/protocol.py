"""Protocol detection and API key extraction."""
import json
from typing import Optional
from app.types.enums import ProtocolFormat


class ProtocolDetector:
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
        except Exception:
            pass
        return ProtocolFormat.OPENAI.value

    @staticmethod
    def extract_api_key(headers: dict) -> Optional[str]:
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
