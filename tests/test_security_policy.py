from dataclasses import replace

import pytest

from app.application.services.misc_services import SecurityService
from app.config import SecuritySettings
from app.domain.security_policy import upgrade_settings


def test_legacy_settings_conversion_preserves_effective_mode():
    for mode in ("audit", "warn", "block", "redact"):
        for flag in (False, True):
            settings = upgrade_settings(SecuritySettings(mode=mode, redact_secrets=flag))
            assert not settings.redact_secrets
            assert settings.mode == ("audit" if mode == "redact" and not flag else mode)


def test_settings_persist_across_repositories_and_snapshot_is_immutable(monkeypatch):
    from test_security_repository import _repository

    from app.infrastructure.repositories.security_repo import SecurityRepository

    repo, _ = _repository(monkeypatch)
    repo.initialize_settings(SecuritySettings(mode="redact", redact_secrets=True))
    repo.seed_builtin_rules()
    service = SecurityService(repo)
    assert service.get_settings()["mode"] == "redact"
    assert not service.get_settings()["redact_secrets"]
    snapshot = repo.snapshot()
    service.update_settings({"mode": "audit", "redact_secrets": True})
    other = SecurityRepository()
    assert other.get_settings().redact_secrets
    assert snapshot.settings.mode == "redact" and not snapshot.settings.redact_secrets
    repo.initialize_settings(SecuritySettings(enabled=False))
    assert other.get_settings().enabled
    assert service.get_settings()["capabilities"]["stream_response_scan"] is False
    for fields in ({}, {"unknown": True}, {"enabled": "false"}, {"mode": "invalid"}):
        with pytest.raises(ValueError):
            repo.update_settings(fields)
    assert repo.get_settings() == replace(snapshot.settings, mode="audit", redact_secrets=True)
