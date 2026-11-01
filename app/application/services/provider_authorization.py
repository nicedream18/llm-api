"""Provider authorization transactions; credentials stay encrypted in storage."""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from app.application.errors import ApplicationError
from app.domain.provider_adapters import config_hash
from app.types.provider import ProviderTokenInput

logger = logging.getLogger(__name__)


class ProviderAuthorization:
    def __init__(self, repository, service, adapter_factory):
        self.repo = repository
        self.service = service
        self.adapter = adapter_factory

    def begin(self, account_id, principal):
        account = self.repo.get_account(account_id)
        if account is None:
            raise ApplicationError("Provider account not found", 404, "not_found")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        url = self.adapter(account["provider"]).authorize_url(self.service._client_config(account), state, challenge)
        now = datetime.now(UTC)
        self.repo.store_oauth({
            "state_hash": hashlib.sha256(state.encode()).hexdigest(), "account_id": account_id,
            "provider": account["provider"], "principal_type": principal[0], "principal_id": principal[1],
            "verifier": self.service._encrypt(verifier), "config_hash": config_hash(account),
            "expires_at": (now + timedelta(minutes=10)).isoformat(), "created_at": now.isoformat(),
        })
        return {"state": state, "authorization_url": url, "expires_in": 600}

    def finish(self, state, code, principal, provider=None, error=None):
        record = self.repo.consume_oauth(hashlib.sha256(state.encode()).hexdigest(), principal, provider)
        if record is None:
            raise ApplicationError("OAuth state is invalid or expired", 400, "invalid_oauth_state")
        if error or not code:
            raise ApplicationError("Provider authorization was not completed", 400, "oauth_authorization_denied")
        account = self.repo.get_account(record["account_id"])
        if account is None:
            raise ApplicationError("Provider account not found", 404, "not_found")
        try:
            token = self.adapter(account["provider"]).exchange_code(self.service._client_config(account), code, self.service._decrypt(record["verifier"]))
            dto = ProviderTokenInput(**token)
        except ApplicationError:
            raise
        except (ValueError, TypeError, RuntimeError):
            raise ApplicationError("Provider authorization failed", 502, "provider_error") from None
        self._save(record["account_id"], dto, record["generation"])
        return self.service._decode(self.repo.get_account(record["account_id"]))

    def _save(self, account_id, dto, generation, owner=None):
        self.repo.store_token(account_id, {
            "access_token": self.service._encrypt(dto.access_token),
            "refresh_token": self.service._encrypt(dto.refresh_token), "expires_at": dto.expires_at,
        }, generation, owner)

    def refresh(self, account_id):
        account = self.repo.get_account(account_id)
        if account is None:
            raise ApplicationError("Provider account is not connected", 404, "not_found")
        owner = secrets.token_hex(24)
        token = self.repo.claim_refresh(account_id, owner)
        try:
            refreshed = self.adapter(account["provider"]).refresh(self.service._client_config(account), self.service._decrypt(token.get("refresh_token")) or "")
            if not refreshed.get("access_token"):
                raise ApplicationError("Provider did not return a refreshed token", 502, "invalid_provider_response")
            dto = ProviderTokenInput(**{**refreshed, "refresh_token": refreshed.get("refresh_token") or self.service._decrypt(token.get("refresh_token"))})
            self._save(account_id, dto, token["generation"], owner)
        except ApplicationError:
            raise
        except (ValueError, TypeError, RuntimeError):
            raise ApplicationError("Provider token refresh failed", 502, "provider_error") from None
        finally:
            self.repo.release_refresh(account_id, owner)
        return self.service._decode(self.repo.get_account(account_id))

    def sign_out(self, account_id):
        account = self.repo.get_account(account_id)
        if account is None:
            raise ApplicationError("Provider account not found", 404, "not_found")
        token = self.repo.get_token(account_id)
        self.repo.delete_token(account_id)
        if token:
            try:
                access_token = self.service._decrypt(token.get("access_token"))
                revoke = getattr(self.adapter(account["provider"]), "revoke", None)
                if callable(revoke):
                    revoke(self.service._client_config(account), access_token)
            except (ApplicationError, ValueError, TypeError, RuntimeError):
                logger.warning("Provider revoke failed after local sign-out")
        return True
