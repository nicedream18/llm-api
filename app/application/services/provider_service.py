"""Provider account lifecycle with encrypted token storage."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cryptography.fernet import Fernet, InvalidToken

from app.application.errors import ApplicationError
from app.application.services.provider_authorization import ProviderAuthorization
from app.config import config
from app.domain.entities import ChannelEntity
from app.domain.provider_adapters import adapter_for
from app.domain.provider_quota import normalize_quota, quota_status

logger = logging.getLogger(__name__)


class ProviderService:
    _SECRET_KEY = re.compile(
        r"(?:client[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|credential|^authorization$|^cookie$|private[_-]?key)",
        re.IGNORECASE,
    )
    _ENV_REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,255}$")

    def __init__(self, repository):
        self.repo = repository
        self.authorization = ProviderAuthorization(repository, self, lambda name: adapter_for(name))

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("client_config", "model_mapping", "tags"):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (TypeError, ValueError, json.JSONDecodeError):
                    result[key] = {}
        result.pop("access_token", None)
        result.pop("refresh_token", None)
        result["enabled"] = bool(result.get("enabled", True))
        result.setdefault("group_name", "")
        result.setdefault("tags", [])
        result["auth_status"] = result.get("status", "pending")
        result["health_status"] = "cooling" if result.get("cooldown_until") and not ProviderService._expired(result["cooldown_until"], skew=0) else "healthy"
        return result

    @staticmethod
    def _cipher():
        configured = config.auth.provider_token_key
        seed = configured or config.auth.session_secret or "development-only-provider-key"
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    def _encrypt(self, value: str | None):
        return self._cipher().encrypt(value.encode("utf-8")).decode("ascii") if value else None

    def _decrypt(self, value: str | None):
        if not value:
            return None
        try:
            return self._cipher().decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            raise ApplicationError("Provider token cannot be decrypted", 503, "configuration_error") from None

    def list_accounts(self):
        return [self._decode(row) for row in self.repo.list_accounts()]

    def create_account(self, dto):
        self._validate_client_config(dto.client_config)
        return self._decode(self.repo.create_account(dto.model_dump()))

    def query_accounts(self, query):
        result = self.repo.query_accounts(query)
        result["items"] = [self._decode(row) for row in result["items"]]
        return result

    def account_detail(self, account_id):
        row = self.repo.get_account(account_id)
        if row is None:
            raise ApplicationError("Provider account not found", 404, "not_found")
        return self._decode({**row, **self.repo.account_profile(account_id)})

    def operate_account(self, account_id, dto):
        try:
            value = dto.value()
        except ValueError as exc:
            raise ApplicationError(str(exc), 422, "invalid_account_operation") from exc
        changed = self.repo.operate_account(account_id, dto.operation, value)
        return {"changed": changed, "account": self.account_detail(account_id)}

    def bulk_accounts(self, dto):
        results = []
        for account_id in dict.fromkeys(dto.account_ids):
            try:
                result = self.operate_account(account_id, dto)
                results.append({"id": account_id, "success": True, "changed": result["changed"]})
            except ApplicationError as exc:
                results.append({"id": account_id, "success": False, "error": exc.code})
        return {"results": results}

    def update_account(self, account_id, dto):
        account = self.repo.get_account(account_id)
        if not account:
            raise ApplicationError("Provider account not found", 404, "not_found")
        if dto.provider != account["provider"] and self.repo.get_token(account_id):
            raise ApplicationError("Sign out before changing provider", 409, "provider_connected")
        values = dto.model_dump(exclude_unset=True)
        if "client_config" in values:
            self._validate_client_config(values["client_config"])
        return self._decode(self.repo.update_account(account_id, values))

    def delete_account(self, account_id):
        return self.repo.delete_account(account_id)

    def set_token(self, account_id, dto):
        if not self.repo.get_account(account_id):
            raise ApplicationError("Provider account not found", 404, "not_found")
        if hasattr(self.repo, "account_profile") and self.repo.account_profile(account_id)["archived_at"]:
            raise ApplicationError("Provider account is archived", 409, "account_archived")
        self.repo.save_token(account_id, {
            "access_token": self._encrypt(dto.access_token),
            "refresh_token": self._encrypt(dto.refresh_token),
            "expires_at": dto.expires_at,
        })
        return self._decode(self.repo.get_account(account_id))

    def authorize(self, account_id, principal=("admin", "system")):
        return self.authorization.begin(account_id, principal)

    def callback(self, state, code, principal=("admin", "system"), provider=None, error=None):
        return self.authorization.finish(state, code, principal, provider, error)

    def sign_out(self, account_id):
        return self.authorization.sign_out(account_id)

    def refresh(self, account_id):
        return self.authorization.refresh(account_id)

    def quota(self, account_id):
        return self._provider_data(account_id, "quota")

    def models(self, account_id):
        return self._provider_data(account_id, "models")

    def record_failure(self, account_id):
        account = self.repo.get_account(account_id)
        if not account or not hasattr(self.repo, "record_failure"):
            return None
        count = int(account.get("failure_count") or 0) + 1
        duration = min(300, 2 ** min(count, 8))
        return self.repo.record_failure(account_id, (datetime.now(UTC) + timedelta(seconds=duration)).isoformat())

    def record_success(self, account_id):
        if hasattr(self.repo, "clear_failures"):
            return self.repo.clear_failures(account_id)
        return None

    @staticmethod
    def _expired(expires_at, skew=30):
        if not expires_at:
            return False
        try:
            value = float(expires_at)
            return value <= datetime.now(UTC).timestamp() + skew
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(str(expires_at))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed <= datetime.now(UTC) + timedelta(seconds=skew)
            except ValueError:
                return False

    def routing_channels(self, model: str, *, preview=False):
        """Expose explicitly configured OAuth accounts as gateway candidates.

        A provider account participates in routing only after it has a token and
        a configured ``gateway_url`` (or ``base_url``). This keeps OAuth account
        management independent from arbitrary upstream discovery.
        """
        result = []
        for row in self.repo.list_accounts():
            if row.get("status") != "active":
                continue
            if hasattr(self.repo, "account_profile"):
                profile = self.repo.account_profile(row["id"])
                if not profile["enabled"] or profile["archived_at"]:
                    continue
            account = self.repo.get_account(row.get("id")) or row
            token_row = self.repo.get_token(row.get("id"))
            if not token_row:
                continue
            if self._expired(token_row.get("expires_at")):
                if preview or not token_row.get("refresh_token"):
                    continue
                try:
                    self.refresh(row["id"])
                    token_row = self.repo.get_token(row["id"])
                except ApplicationError:
                    self.record_failure(row["id"])
                    continue
            cooldown_until = account.get("cooldown_until")
            if cooldown_until and not self._expired(cooldown_until, skew=0):
                continue
            try:
                client_config = self._client_config(account)
                if not isinstance(client_config, dict):
                    continue
                base_url = client_config.get("gateway_url") or client_config.get("base_url")
                if not isinstance(base_url, str) or not base_url.strip():
                    continue
                mapping = account.get("model_mapping") or {}
                if isinstance(mapping, str):
                    mapping = json.loads(mapping)
                if not isinstance(mapping, dict):
                    mapping = {}
                upstream_model = mapping.get(model, model)
                models = [str(key) for key in mapping if key]
                quota_info = self._routing_quota(account["id"])
                if quota_info["quota_status"] == "exhausted":
                    continue
                if models and model not in models:
                    continue
                access_token = "preview" if preview else self._decrypt(token_row.get("access_token"))
                if not access_token:
                    continue
                result.append(ChannelEntity(
                    id=f"provider:{account['id']}",
                    name=f"provider:{account.get('name') or account['id']}",
                    type=str(client_config.get("channel_type") or "openai"),
                    base_url=base_url.rstrip("/"),
                    api_key=access_token,
                    models=models,
                    priority=int(account.get("priority") or 0),
                    weight=1,
                    model_mapping={model: upstream_model} if upstream_model != model else {},
                    config={"provider_account_id": account["id"], "provider": account["provider"],
                            "endpoints": client_config.get("endpoints", ["/v1/chat/completions"]), **quota_info},
                ))
            except (ApplicationError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    def _routing_quota(self, account_id):
        if not hasattr(self.repo, "synchronization_state"):
            return {"quota_status": "unknown", "quota_fraction": 0.1}
        state = self.repo.synchronization_state(account_id)
        quota = state["snapshots"].get("quota")
        if not quota or not quota["payload"] or quota["generation"] != state["generation"]:
            return {"quota_status": "unknown", "quota_fraction": 0.1}
        value = quota["payload"]
        status = quota_status({**value, "fetched_at": quota["fetched_at"]})
        fractions = [Decimal(window["remaining"]) / Decimal(window["limit"]) for window in value.get("windows", [])
                     if window.get("remaining") is not None and window.get("limit") and window.get("unit") != "unknown"]
        return {"quota_status": status, "quota_fraction": float(max(Decimal("0.01"), min(fractions))) if fractions and status in {"normal", "low"} else 0.1}

    def _provider_data(self, account_id, operation, job=None):
        account = self.repo.get_account(account_id)
        token = self.repo.get_token(account_id) if account else None
        if not account or not token:
            raise ApplicationError("Provider account is not connected", 404, "not_found")
        if self._expired(token.get("expires_at")):
            self.refresh(account_id)
        generation = None
        if hasattr(self.repo, "read_sync_credentials"):
            account, token, generation = self.repo.read_sync_credentials(account_id)
        else:
            token = self.repo.get_token(account_id)
        adapter = adapter_for(account["provider"])
        access_token = self._decrypt(token.get("access_token")) or ""
        requested_at = datetime.now(UTC).isoformat()
        try:
            value = getattr(adapter, operation)(self._client_config(account), access_token)
            secrets_to_hide = [access_token, self._decrypt(token.get("refresh_token"))]
            value = self._redact_provider_value(value, secrets_to_hide)
            normalized = {"models": value} if operation == "models" else normalize_quota(value)
        except ApplicationError as exc:
            if generation is not None:
                self.repo.save_snapshot(account_id, operation, generation, error=exc.code, job=job, requested_at=requested_at)
            raise
        except Exception as exc:
            if generation is not None:
                self.repo.save_snapshot(account_id, operation, generation, error="provider_error", job=job, requested_at=requested_at)
            raise ApplicationError("Provider endpoint request failed", 502, "provider_error") from exc
        if generation is not None:
            self.repo.save_snapshot(account_id, operation, generation, normalized, job=job, requested_at=requested_at)
        if operation == "models":
            return {"models": value}
        return value

    @classmethod
    def _redact_provider_value(cls, value, secrets_to_hide):
        if isinstance(value, dict):
            return {key: cls._redact_provider_value(child, secrets_to_hide) for key, child in value.items() if not cls._SECRET_KEY.search(key)}
        if isinstance(value, list):
            return [cls._redact_provider_value(child, secrets_to_hide) for child in value if not isinstance(child, str) or not any(secret and secret in child for secret in secrets_to_hide)]
        if isinstance(value, str):
            for secret in secrets_to_hide:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
        return value

    def sync_state(self, account_id):
        self.account_detail(account_id)
        state = self.repo.synchronization_state(account_id)
        quota = state["snapshots"].get("quota")
        if quota and quota["payload"]:
            quota["payload"]["status"] = "stale" if quota["generation"] != state["generation"] else quota_status({**quota["payload"], "fetched_at": quota["fetched_at"]})
        return state

    @classmethod
    def _validate_client_config(cls, value, key_path="client_config"):
        if not isinstance(value, dict):
            raise ApplicationError("Provider client configuration must be an object", 422, "invalid_provider_config")
        for key, child in value.items():
            if cls._SECRET_KEY.search(str(key)) and isinstance(child, str):
                raise ApplicationError(
                    f"Provider secret '{key_path}.{key}' must use an environment reference",
                    422,
                    "provider_secret_reference_required",
                )
            cls._validate_client_value(child, f"{key_path}.{key}")

    @classmethod
    def _validate_client_value(cls, value, key_path):
        if isinstance(value, dict):
            if set(value) == {"env"}:
                name = value["env"]
                if not isinstance(name, str) or not cls._ENV_REFERENCE.fullmatch(name):
                    raise ApplicationError("Provider environment reference is invalid", 422, "invalid_provider_config")
                return
            for key, child in value.items():
                if cls._SECRET_KEY.search(str(key)) and isinstance(child, str):
                    raise ApplicationError(
                        f"Provider secret '{key_path}.{key}' must use an environment reference",
                        422,
                        "provider_secret_reference_required",
                    )
                cls._validate_client_value(child, f"{key_path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                cls._validate_client_value(child, f"{key_path}[{index}]")

    @classmethod
    def _resolve_client_value(cls, value, key_path="client_config"):
        if isinstance(value, dict):
            if set(value) == {"env"}:
                name = value["env"]
                if not isinstance(name, str) or not cls._ENV_REFERENCE.fullmatch(name):
                    raise ApplicationError("Provider environment reference is invalid", 422, "invalid_provider_config")
                resolved = os.getenv(name)
                if resolved is None:
                    raise ApplicationError(f"Provider environment variable '{name}' is not configured", 503, "provider_secret_unavailable")
                return resolved
            return {key: cls._resolve_client_value(child, f"{key_path}.{key}") for key, child in value.items()}
        if isinstance(value, list):
            return [cls._resolve_client_value(child, f"{key_path}[{index}]") for index, child in enumerate(value)]
        return value

    @classmethod
    def _client_config(cls, account):
        raw = account.get("client_config") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ApplicationError("Provider client configuration is invalid", 422, "invalid_provider_config") from exc
        cls._validate_client_config(raw)
        return cls._resolve_client_value(raw)
