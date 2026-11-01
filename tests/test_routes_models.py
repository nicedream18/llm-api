from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_models_aggregates_channels_and_provider_mappings(monkeypatch):
    from app.api.controllers import routes

    class Channels:
        def get_enabled_channels(self):
            return [SimpleNamespace(id="channel", name="demo", models=["channel-model"])]

    class Providers:
        def list_accounts(self):
            return [
                {"status": "active", "model_mapping": '{"provider-model":"upstream-model"}'},
                {"status": "signed_out", "model_mapping": {"hidden": "hidden-upstream"}},
            ]

    monkeypatch.setattr(routes, "get_container", lambda: SimpleNamespace(channel_repo=Channels(), provider_repo=Providers()))
    request = SimpleNamespace(state=SimpleNamespace(auth_context=None))

    payload = await routes.models(request)

    assert [row["id"] for row in payload["data"]] == ["channel-model", "provider-model", "upstream-model"]


@pytest.mark.asyncio
async def test_models_applies_api_key_model_allowlist(monkeypatch):
    from app.api.controllers import routes
    from app.types.auth import AuthContext

    monkeypatch.setattr(routes, "get_container", lambda: SimpleNamespace(
        channel_repo=SimpleNamespace(get_enabled_channels=lambda: [SimpleNamespace(id="channel", name="demo", models=["allowed", "blocked"])]),
        provider_repo=SimpleNamespace(list_accounts=list),
    ))
    request = SimpleNamespace(state=SimpleNamespace(auth_context=AuthContext("api_key", "key", "client", allowed_models=frozenset({"allowed"}))))

    payload = await routes.models(request)

    assert payload["data"] == [{"id": "allowed", "object": "model", "owned_by": "waliapi"}]
