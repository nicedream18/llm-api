"""Provider adapter contract shared by OAuth, refresh, quota and model sync."""

from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlencode


class ProviderAdapter(ABC):
    def __init__(self, provider: str):
        self.provider = provider

    def authorize_url(self, config: dict, state: str, code_challenge: str) -> str:
        base = str(config.get("authorization_url") or "")
        if not base:
            return ""
        params = {
            "client_id": config.get("client_id", ""),
            "redirect_uri": config.get("redirect_uri", ""),
            "response_type": "code",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return base + ("&" if "?" in base else "?") + urlencode(params)

    @abstractmethod
    def exchange_code(self, config: dict, code: str, verifier: str) -> dict:
        raise NotImplementedError

    def refresh(self, config: dict, refresh_token: str) -> dict:
        return {"refresh_token": refresh_token}

    def revoke(self, config: dict, access_token: str) -> None:
        return None

    def quota(self, config: dict, access_token: str) -> dict:
        return {}

    def models(self, config: dict, access_token: str) -> list[str]:
        return []


class ConfiguredProviderAdapter(ProviderAdapter):
    """Provider adapter with deterministic mockable token behavior."""

    def exchange_code(self, config: dict, code: str, verifier: str) -> dict:
        if not code or not verifier:
            raise ValueError("Authorization code and verifier are required")
        # Real provider endpoints can be added without changing account storage.
        return {"access_token": code, "refresh_token": None, "expires_at": None}


def adapter_for(provider: str) -> ProviderAdapter:
    if provider not in {"codex", "gemini", "grok", "kimi", "qoder", "workbuddy"}:
        raise ValueError("Unsupported provider")
    return ConfiguredProviderAdapter(provider)
