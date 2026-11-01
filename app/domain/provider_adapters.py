"""Provider adapter contract shared by OAuth, refresh, quota and model sync."""

from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlencode

import httpx


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
    """Provider adapter with configurable HTTP endpoints and test fallback."""

    def exchange_code(self, config: dict, code: str, verifier: str) -> dict:
        if not code or not verifier:
            raise ValueError("Authorization code and verifier are required")
        token_url = str(config.get("token_url") or config.get("token_endpoint") or "")
        if token_url:
            payload = {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "client_id": config.get("client_id", ""),
                "redirect_uri": config.get("redirect_uri", ""),
            }
            if config.get("client_secret"):
                payload["client_secret"] = config["client_secret"]
            return self._token_request(token_url, payload, config)
        # Development fallback retained for deterministic local tests.
        return {"access_token": code, "refresh_token": None, "expires_at": None}

    def refresh(self, config: dict, refresh_token: str) -> dict:
        if not refresh_token:
            raise ValueError("Refresh token is required")
        token_url = str(config.get("token_url") or config.get("token_endpoint") or "")
        if not token_url:
            return {"refresh_token": refresh_token}
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config.get("client_id", ""),
        }
        if config.get("client_secret"):
            payload["client_secret"] = config["client_secret"]
        return self._token_request(token_url, payload, config)

    def quota(self, config: dict, access_token: str) -> dict:
        url = str(config.get("quota_url") or "")
        if not url:
            return {}
        payload = self._json_request(url, access_token, config)
        return payload if isinstance(payload, dict) else {"value": payload}

    def models(self, config: dict, access_token: str) -> list[str]:
        url = str(config.get("models_url") or "")
        if not url:
            return []
        payload = self._json_request(url, access_token, config)
        values = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
        if not isinstance(values, list):
            return []
        result = []
        for value in values:
            name = value.get("id") if isinstance(value, dict) else value
            if isinstance(name, str) and name.strip() and name.strip() not in result:
                result.append(name.strip())
        return result

    @staticmethod
    def _timeout(config: dict) -> float:
        try:
            return min(max(float(config.get("timeout_seconds", 15)), 1.0), 120.0)
        except (TypeError, ValueError):
            return 15.0

    @classmethod
    def _token_request(cls, url: str, payload: dict, config: dict) -> dict:
        try:
            response = httpx.post(url, data=payload, timeout=cls._timeout(config), follow_redirects=False)
        except httpx.HTTPError as exc:
            raise ValueError("Provider token endpoint is unavailable") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ValueError("Provider token endpoint rejected the request")
        try:
            result = response.json()
        except ValueError as exc:
            raise ValueError("Provider token endpoint returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise TypeError("Provider token response must be an object")
        if not isinstance(result.get("access_token"), str):
            raise TypeError("Provider token response is missing access_token")
        return {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token"),
            "expires_at": result.get("expires_at") or result.get("expires_in"),
        }

    @classmethod
    def _json_request(cls, url: str, access_token: str, config: dict):
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=cls._timeout(config),
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise ValueError("Provider endpoint is unavailable") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ValueError("Provider endpoint rejected the request")
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError("Provider endpoint returned invalid JSON") from exc


def adapter_for(provider: str) -> ProviderAdapter:
    if provider not in {"codex", "gemini", "grok", "kimi", "qoder", "workbuddy"}:
        raise ValueError("Unsupported provider")
    return ConfiguredProviderAdapter(provider)
