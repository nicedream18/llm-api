import json

import pytest

from app.application.errors import ApplicationError
from app.application.services.provider_service import ProviderService
from app.types.provider import ProviderAccountInput, ProviderTokenInput


class MemoryProviderRepository:
    def __init__(self):
        self.accounts = {}
        self.tokens = {}

    def create_account(self, values):
        account = {"id": "provider-1", "status": "disconnected", **values}
        account["client_config"] = json.dumps(account["client_config"])
        account["model_mapping"] = json.dumps(account["model_mapping"])
        self.accounts[account["id"]] = account
        return account

    def list_accounts(self):
        return list(self.accounts.values())

    def get_account(self, account_id):
        return self.accounts.get(account_id)

    def update_account(self, account_id, values):
        account = self.accounts.get(account_id)
        if not account:
            return None
        account.update(values)
        for key in ("client_config", "model_mapping"):
            if isinstance(account.get(key), dict):
                account[key] = json.dumps(account[key])
        return account

    def delete_account(self, account_id):
        self.tokens.pop(account_id, None)
        return self.accounts.pop(account_id, None) is not None

    def save_token(self, account_id, values):
        self.tokens[account_id] = values
        self.accounts[account_id]["status"] = "active"

    def get_token(self, account_id):
        return self.tokens.get(account_id)

    def delete_token(self, account_id):
        self.tokens.pop(account_id, None)
        if account_id in self.accounts:
            self.accounts[account_id]["status"] = "disconnected"


def test_provider_account_oauth_refresh_and_metadata_lifecycle(monkeypatch):
    from app.application.services import provider_service

    repo = MemoryProviderRepository()
    service = ProviderService(repo)
    config = {
        "authorization_url": "https://accounts.example/authorize",
        "client_id": "public-client",
        "token_url": "https://accounts.example/token",
    }
    account = service.create_account(ProviderAccountInput(
        provider="gemini", name="Primary", client_config=config,
        model_mapping={"public-model": "provider-model"}, priority=10,
    ))
    assert account["client_config"] == config
    assert account["model_mapping"] == {"public-model": "provider-model"}
    assert service.list_accounts()[0]["id"] == account["id"]
    assert service.update_account(account["id"], ProviderAccountInput(
        provider="gemini", name="Updated", priority=20,
    ))["name"] == "Updated"

    class Adapter:
        def authorize_url(self, _config, state, challenge):
            return f"https://accounts.example/authorize?state={state}&challenge={challenge}"

        def exchange_code(self, _config, code, verifier):
            assert code == "one-use-code" and verifier
            return {"access_token": "access-from-oauth", "refresh_token": "refresh-from-oauth"}

        def refresh(self, _config, refresh_token):
            assert refresh_token == "refresh-from-oauth"
            return {"access_token": "rotated-access"}

        def quota(self, _config, access_token):
            return {"remaining": 12, "token_seen": access_token}

        def models(self, _config, access_token):
            return ["model-a", access_token]

    monkeypatch.setattr(provider_service, "adapter_for", lambda _provider: Adapter())
    authorization = service.authorize(account["id"])
    assert authorization["state"] in service._oauth_states
    connected = service.callback(authorization["state"], "one-use-code")
    assert connected["status"] == "active"
    assert "access_token" not in connected and "refresh_token" not in connected
    encrypted = repo.get_token(account["id"])
    assert encrypted["access_token"] != "access-from-oauth"
    assert service.refresh(account["id"])["status"] == "active"
    rotated = repo.get_token(account["id"])
    assert service._decrypt(rotated["access_token"]) == "rotated-access"
    assert service._decrypt(rotated["refresh_token"]) == "refresh-from-oauth"
    assert service.quota(account["id"])["remaining"] == 12
    assert service.models(account["id"])["models"] == ["model-a", "rotated-access"]
    assert repo.get_account(account["id"])["status"] == "active"

    service.sign_out(account["id"])
    assert repo.get_token(account["id"]) is None
    assert repo.get_account(account["id"])["status"] == "disconnected"
    assert service.delete_account(account["id"]) is True
    assert service.delete_account(account["id"]) is False


def test_provider_service_rejects_missing_accounts_tokens_and_failed_upstream(monkeypatch):
    from app.application.services import provider_service

    repo = MemoryProviderRepository()
    service = ProviderService(repo)
    with pytest.raises(ApplicationError, match="not found"):
        service.set_token("missing", ProviderTokenInput(access_token="secret"))
    with pytest.raises(ApplicationError, match="not found"):
        service.authorize("missing")
    with pytest.raises(ApplicationError, match="not connected"):
        service.refresh("missing")
    with pytest.raises(ApplicationError, match="not connected"):
        service.quota("missing")

    account = service.create_account(ProviderAccountInput(provider="gemini", name="Broken"))

    class FailingAdapter:
        def authorize_url(self, *_args):
            return "https://accounts.example/authorize"

        def exchange_code(self, *_args):
            raise RuntimeError("private upstream error")

        def refresh(self, *_args):
            raise RuntimeError("private upstream error")

        def quota(self, *_args):
            raise RuntimeError("private upstream error")

        def models(self, *_args):
            raise RuntimeError("private upstream error")

    monkeypatch.setattr(provider_service, "adapter_for", lambda _provider: FailingAdapter())
    auth = service.authorize(account["id"])
    with pytest.raises(ApplicationError, match="authorization failed") as err:
        service.callback(auth["state"], "code")
    assert "private upstream error" not in str(err.value)
    assert auth["state"] not in service._oauth_states

    service.set_token(account["id"], ProviderTokenInput(access_token="access", refresh_token="refresh"))
    with pytest.raises(ApplicationError, match="refresh failed"):
        service.refresh(account["id"])
    with pytest.raises(ApplicationError, match="endpoint request failed"):
        service.quota(account["id"])
    with pytest.raises(ApplicationError, match="endpoint request failed"):
        service.models(account["id"])

    repo.tokens[account["id"]]["access_token"] = "tampered-ciphertext"
    with pytest.raises(ApplicationError, match="cannot be decrypted"):
        service.quota(account["id"])


def test_provider_accounts_become_gateway_candidates_only_when_explicitly_configured():
    repo = MemoryProviderRepository()
    service = ProviderService(repo)
    account = service.create_account(ProviderAccountInput(
        provider="codex", name="Routeable", client_config={"gateway_url": "https://gateway.example", "channel_type": "openai"},
        model_mapping={"public-model": "upstream-model"}, priority=7,
    ))
    assert service.routing_channels("public-model") == []
    service.set_token(account["id"], ProviderTokenInput(access_token="oauth-access"))
    channels = service.routing_channels("public-model")
    assert len(channels) == 1
    assert channels[0].id == f"provider:{account['id']}"
    assert channels[0].base_url == "https://gateway.example"
    assert channels[0].api_key == "oauth-access"
    assert channels[0].model_mapping == {"public-model": "upstream-model"}
    assert service.routing_channels("other-model") == []


def test_provider_routing_skips_accounts_without_gateway_or_with_invalid_token():
    repo = MemoryProviderRepository()
    service = ProviderService(repo)
    no_gateway = service.create_account(ProviderAccountInput(provider="gemini", name="No route"))
    service.set_token(no_gateway["id"], ProviderTokenInput(access_token="token"))
    assert service.routing_channels("any") == []
    repo.tokens[no_gateway["id"]]["access_token"] = "tampered"
    assert service.routing_channels("any") == []

