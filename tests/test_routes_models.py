from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_models_aggregates_channels_and_provider_mappings(monkeypatch):
    from app.api.controllers import routes

    class Channels:
        def get_enabled_channels(self):
            return [SimpleNamespace(id="channel", name="demo", models=["channel-model"])]

    class Providers:
        def routing_channels(self, model, *, preview):
            assert model is None and preview is True
            return [SimpleNamespace(id="provider:a", name="account", models=[], model_mapping={"provider-model": "upstream-model"})]

    monkeypatch.setattr(routes, "get_container", lambda: SimpleNamespace(channel_repo=Channels(), provider_service=Providers()))
    request = SimpleNamespace(state=SimpleNamespace(auth_context=None))

    payload = await routes.models(request)

    assert [row["id"] for row in payload["data"]] == ["channel-model", "provider-model"]


@pytest.mark.asyncio
async def test_models_applies_api_key_model_allowlist(monkeypatch):
    from app.api.controllers import routes
    from app.types.auth import AuthContext

    monkeypatch.setattr(routes, "get_container", lambda: SimpleNamespace(
        channel_repo=SimpleNamespace(get_enabled_channels=lambda: [SimpleNamespace(id="channel", name="demo", models=["allowed", "blocked"])]),
        provider_service=SimpleNamespace(routing_channels=lambda *args, **kwargs: []),
    ))
    request = SimpleNamespace(state=SimpleNamespace(auth_context=AuthContext("api_key", "key", "client", allowed_models=frozenset({"allowed"}))))

    payload = await routes.models(request)

    assert payload["data"] == [{"id": "allowed", "object": "model", "owned_by": "waliapi"}]
