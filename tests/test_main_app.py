from types import SimpleNamespace

from fastapi import Request
from fastapi.testclient import TestClient

from app import main


def test_public_landing_and_assets_do_not_require_admin_or_database(monkeypatch):
    def unexpected_container():
        raise AssertionError("Public landing must not initialize the database container")

    monkeypatch.setattr("app.api.middleware.auth.get_container", unexpected_container)
    client = TestClient(main.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "让灵感，快一步成为产品" in response.text
    assert 'content="WaLiAPI，为独立开发者准备的 AI 工作台' in response.text
    response = client.get("/landing/favicon.svg")
    assert response.status_code == 200 and "<svg" in response.text


def test_public_landing_does_not_make_admin_api_public(monkeypatch):
    container = SimpleNamespace(channel_repo=None, admin_service=SimpleNamespace(auth=SimpleNamespace(verify_admin_token=lambda token: None)))
    monkeypatch.setattr("app.api.middleware.auth.get_container", lambda: container)
    client = TestClient(main.app)
    assert client.get("/api/v1/security/settings").status_code == 401


def test_main_app_registers_expected_platform_routes():
    paths = {route.path for route in main.app.routes}

    assert "/v1/chat/completions" in paths
    assert "/mcp" in paths
    assert "/api/v1/kb/{kb_id}/documents/upload" in paths
    assert "/api/v1/wiki/projects/{project_id}/pages" in paths
    assert "/api/v1/software/tools/{tool_id}/invoke" in paths
    assert "/api/v1/providers/{account_id}/authorize" in paths
    assert "/api/v1/platform/prompts/{prompt_id}/render" in paths


def test_lifespan_applies_migrations_starts_worker_and_closes_resources(monkeypatch):
    calls = []

    class Worker:
        async def start(self):
            calls.append("worker-start")

        async def stop(self):
            calls.append("worker-stop")

    class Gateway:
        async def aclose(self):
            calls.append("gateway-close")

    container = SimpleNamespace(security_repo=SimpleNamespace(seed_builtin_rules=lambda: calls.append("seed"), initialize_settings=lambda: calls.append("settings")), quota_recovery_worker=Worker(), kb_worker=Worker(), provider_sync_worker=Worker(), operations_worker=Worker(), gateway=Gateway())
    monkeypatch.setattr(main, "apply_migrations", lambda: calls.append("migrations"))
    monkeypatch.setattr(main, "get_container", lambda: container)

    async def run_lifespan():
        async with main.lifespan(main.app):
            calls.append("serving")

    import asyncio

    asyncio.run(run_lifespan())

    assert calls == ["migrations", "seed", "settings", "worker-start", "worker-start", "worker-start", "worker-start", "serving", "worker-stop", "worker-stop", "worker-stop", "worker-stop", "gateway-close"]


def test_lifespan_keeps_shutdown_alive_if_gateway_close_fails(monkeypatch):
    calls = []

    class Worker:
        async def start(self):
            calls.append("worker-start")

        async def stop(self):
            calls.append("worker-stop")

    class Gateway:
        async def aclose(self):
            raise RuntimeError("close failed")

    monkeypatch.setattr(main, "apply_migrations", lambda: None)
    monkeypatch.setattr(
        main, "get_container", lambda: SimpleNamespace(security_repo=SimpleNamespace(seed_builtin_rules=lambda: None, initialize_settings=lambda: None), quota_recovery_worker=Worker(), kb_worker=Worker(), provider_sync_worker=Worker(), operations_worker=Worker(), gateway=Gateway())
    )

    async def run_lifespan():
        async with main.lifespan(main.app):
            calls.append("serving")

    import asyncio

    asyncio.run(run_lifespan())

    assert calls == ["worker-start", "worker-start", "worker-start", "worker-start", "serving", "worker-stop", "worker-stop", "worker-stop", "worker-stop"]


def test_global_exception_handler_does_not_expose_exception_message():
    request = Request({"type": "http", "method": "GET", "path": "/test", "headers": [], "query_string": b"", "server": ("test", 80), "scheme": "http", "client": ("test", 1), "root_path": "", "app": main.app})
    request.state.request_id = "request-123"

    import asyncio

    response = asyncio.run(
        main.global_exception_handler(request, RuntimeError("secret upstream details"))
    )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "request-123"
    assert response.body == b'{"code":"0001","info":"Internal server error","data":null}'
