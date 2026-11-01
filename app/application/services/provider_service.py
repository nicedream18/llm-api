"""Provider account lifecycle with encrypted token storage."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from app.application.errors import ApplicationError
from app.config import config
from app.domain.entities import ChannelEntity
from app.domain.provider_adapters import adapter_for


class ProviderService:
    def __init__(self, repository):
        self.repo = repository
        self._oauth_states: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("client_config", "model_mapping"):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (TypeError, ValueError, json.JSONDecodeError):
                    result[key] = {}
        result.pop("access_token", None)
        result.pop("refresh_token", None)
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
        return self._decode(self.repo.create_account(dto.model_dump()))

    def update_account(self, account_id, dto):
        return self._decode(self.repo.update_account(account_id, dto.model_dump(exclude_unset=True)))

    def delete_account(self, account_id):
        return self.repo.delete_account(account_id)

    def set_token(self, account_id, dto):
        if not self.repo.get_account(account_id):
            raise ApplicationError("Provider account not found", 404, "not_found")
        self.repo.save_token(account_id, {
            "access_token": self._encrypt(dto.access_token),
            "refresh_token": self._encrypt(dto.refresh_token),
            "expires_at": dto.expires_at,
        })
        return self._decode(self.repo.get_account(account_id))

    def authorize(self, account_id):
        account = self.repo.get_account(account_id)
        if not account:
            raise ApplicationError("Provider account not found", 404, "not_found")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        self._oauth_states[state] = (account_id, verifier)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        adapter = adapter_for(account["provider"])
        return {"state": state, "authorization_url": adapter.authorize_url(json.loads(account["client_config"]), state, challenge)}

    def callback(self, state, code):
        record = self._oauth_states.pop(state, None)
        if not record:
            raise ApplicationError("OAuth state is invalid or expired", 400, "invalid_oauth_state")
        account_id, verifier = record
        account = self.repo.get_account(account_id)
        if not account:
            raise ApplicationError("Provider account not found", 404, "not_found")
        try:
            token = adapter_for(account["provider"]).exchange_code(json.loads(account["client_config"]), code, verifier)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("Provider authorization failed", 502, "provider_error") from exc
        from app.types.provider import ProviderTokenInput
        return self.set_token(account_id, ProviderTokenInput(**token))

    def sign_out(self, account_id):
        self.repo.delete_token(account_id)
        return True

    def refresh(self, account_id):
        account = self.repo.get_account(account_id)
        token = self.repo.get_token(account_id) if account else None
        if not account or not token:
            raise ApplicationError("Provider account is not connected", 404, "not_found")
        try:
            refreshed = adapter_for(account["provider"]).refresh(json.loads(account["client_config"]), self._decrypt(token.get("refresh_token")) or "")
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("Provider token refresh failed", 502, "provider_error") from exc
        if refreshed.get("access_token"):
            from app.types.provider import ProviderTokenInput
            self.set_token(account_id, ProviderTokenInput(**{**refreshed, "refresh_token": refreshed.get("refresh_token") or self._decrypt(token.get("refresh_token"))}))
        return self._decode(self.repo.get_account(account_id))

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
    def _expired(expires_at):
        if not expires_at:
            return False
        try:
            value = float(expires_at)
            return value <= datetime.now(UTC).timestamp() + 30
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(str(expires_at))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return parsed <= datetime.now(UTC) + timedelta(seconds=30)
            except ValueError:
                return False

    def routing_channels(self, model: str):
        """Expose explicitly configured OAuth accounts as gateway candidates.

        A provider account participates in routing only after it has a token and
        a configured ``gateway_url`` (or ``base_url``). This keeps OAuth account
        management independent from arbitrary upstream discovery.
        """
        result = []
        for row in self.repo.list_accounts():
            if row.get("status") != "active":
                continue
            account = self.repo.get_account(row.get("id")) or row
            token_row = self.repo.get_token(row.get("id"))
            if not token_row:
                continue
            if self._expired(token_row.get("expires_at")):
                if not token_row.get("refresh_token"):
                    continue
                try:
                    self.refresh(row["id"])
                    token_row = self.repo.get_token(row["id"])
                except ApplicationError:
                    self.record_failure(row["id"])
                    continue
            cooldown_until = account.get("cooldown_until")
            if cooldown_until and not self._expired(cooldown_until):
                continue
            try:
                client_config = account.get("client_config") or {}
                if isinstance(client_config, str):
                    client_config = json.loads(client_config)
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
                if models and model not in models:
                    continue
                access_token = self._decrypt(token_row.get("access_token"))
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
                    config={"provider_account_id": account["id"]},
                ))
            except (ApplicationError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return result

    def _provider_data(self, account_id, operation):
        account = self.repo.get_account(account_id)
        token = self.repo.get_token(account_id) if account else None
        if not account or not token:
            raise ApplicationError("Provider account is not connected", 404, "not_found")
        adapter = adapter_for(account["provider"])
        access_token = self._decrypt(token.get("access_token")) or ""
        try:
            value = getattr(adapter, operation)(json.loads(account["client_config"]), access_token)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("Provider endpoint request failed", 502, "provider_error") from exc
        if operation == "models":
            self.repo.update_account(account_id, {"status": "active"})
            return {"models": value}
        return value
