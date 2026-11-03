from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import routes
from app.api.middleware.auth import ApiKeyAuthMiddleware
from app.application.services.misc_services import SecurityService


def client_for(monkeypatch, auth=False):
    from test_security_repository import _repository

    repo, _ = _repository(monkeypatch)
    repo.seed_builtin_rules()
    repo.initialize_settings()
    monkeypatch.setattr(routes, "get_container", lambda: SimpleNamespace(security_service=SecurityService(repo)))
    app = FastAPI()
    app.include_router(routes.security_router)
    if auth:
        app.add_middleware(ApiKeyAuthMiddleware)
    return TestClient(app), repo


def test_security_endpoints_validate_persist_and_reset(monkeypatch):
    client, repo = client_for(monkeypatch)
    settings = client.get("/api/v1/security/settings").json()["data"]
    assert settings["redact_secrets"] is False
    assert client.put("/api/v1/security/settings", json={"redact_secrets": True}).json()["data"]["redact_secrets"]
    assert client.put("/api/v1/security/settings", json={"enabled": "no"}).status_code == 422
    rule = client.get("/api/v1/security/rules/builtin").json()["data"][0]
    endpoint = f'/api/v1/security/rules/builtin/{rule["id"]}'
    assert client.put(endpoint, json={"name": "Company rule", "enabled": False, "severity": "LOW", "action": "WARN"}).json()["data"]
    assert client.put(endpoint, json={"pattern": ".*"}).status_code == 422
    assert client.post("/api/v1/security/rules/builtin/reset").json()["data"]
    assert next(r for r in repo.get_all_builtin_rules() if r.id == rule["id"]).enabled == 1
    custom = client.post("/api/v1/security/rules/custom", json={"name": "Company", "category": "domain", "pattern": "example.com", "rule_type": "whitelist"}).json()["data"]
    assert custom["action"] == "allow" and custom["match_type"] == "literal"
    endpoint = f'/api/v1/security/rules/custom/{custom["id"]}'
    assert client.put(endpoint, json={"enabled": False}).json()["data"]
    assert repo.get_all_custom_rules()[0].pattern == "example.com"
    assert client.delete(endpoint).json()["data"]
    assert client.post("/api/v1/security/rules/custom", json={"pattern": "[", "match_type": "regex"}).status_code == 422


def test_security_management_requires_admin_authentication(monkeypatch):
    client, _ = client_for(monkeypatch, auth=True)
    for method, path, body in [
        ("GET", "/settings", None), ("PUT", "/settings", {"enabled": False}),
        ("GET", "/rules/builtin", None), ("POST", "/rules/builtin/reset", {}),
        ("POST", "/rules/custom", {"pattern": "x"}),
    ]:
        assert client.request(method, "/api/v1/security" + path, json=body).status_code == 401
