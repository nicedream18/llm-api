import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from test_mysql_integration import mysql_engine

from app.config import SecuritySettings
from app.domain.entities import SecurityCustomRuleEntity
from app.domain.security_catalog import BUILTIN_RULES
from app.infrastructure.database import migrations
from app.infrastructure.repositories.security_repo import SecurityRepository

pytestmark = pytest.mark.skipif(
    not (os.environ.get("WALIAPI_TEST_MYSQL_SOCKET") or os.environ.get("WALIAPI_TEST_MYSQL_HOST")),
    reason="Requires an explicitly configured isolated MySQL server",
)


@pytest.fixture
def security_mysql_engine(monkeypatch):
    yield from mysql_engine.__wrapped__(monkeypatch)


def repository(monkeypatch, engine):
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    @contextmanager
    def get_db():
        with sessions.begin() as db:
            yield db
    monkeypatch.setattr("app.infrastructure.repositories.security_repo.get_db", get_db)
    return SecurityRepository()


def test_mysql_concurrent_seed_and_settings_preserve_user_configuration(security_mysql_engine, monkeypatch):
    migrations.apply_migrations()
    repo = repository(monkeypatch, security_mysql_engine)
    def seed(_):
        repo.seed_builtin_rules()
        repo.initialize_settings(SecuritySettings(mode="redact", redact_secrets=True))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(seed, range(8)))
    assert len(repo.get_all_builtin_rules()) == len(BUILTIN_RULES)
    rule = repo.get_all_builtin_rules()[0]
    repo.update_builtin_rule(rule.id, 0, "critical", name="Company override")
    repo.update_settings({"redact_secrets": True, "scan_network": False})
    repo.seed_builtin_rules()
    repo.initialize_settings(SecuritySettings(enabled=False))
    snapshot = repo.snapshot()
    assert snapshot.settings.enabled and snapshot.settings.redact_secrets and not snapshot.settings.scan_network
    assert next(r for r in snapshot.builtin_rules if r.id == rule.id).name == "Company override"
    custom = repo.create_custom_rule(SecurityCustomRuleEntity(category="domain", rule_type="whitelist", pattern="example.com", action="allow"))
    repo.reset_builtin_rules()
    assert repo.get_all_custom_rules()[0].id == custom.id


def test_mysql_upgrade_legacy_regex_and_preserve_builtin_id(security_mysql_engine, monkeypatch):
    with security_mysql_engine.begin() as db:
        db.execute(text("ALTER TABLE security_custom_rules DROP COLUMN match_type"))
        db.execute(text("INSERT INTO security_custom_rules (id,name,pattern,rule_type,action,created_at) VALUES ('legacy','Legacy','a.b','regex','allow','now')"))
        db.execute(text("INSERT INTO security_builtin_rules (id,rule_id,name,severity,enabled,created_at) VALUES ('company-id','credential_jwt','Company JWT','critical',0,'now')"))
    migrations.apply_migrations()
    migrations.apply_migrations()
    repo = repository(monkeypatch, security_mysql_engine)
    repo.seed_builtin_rules()
    custom = repo.get_all_custom_rules()[0]
    assert (custom.rule_type, custom.match_type, custom.action) == ("blacklist", "regex", "allow")
    rule = next(r for r in repo.get_all_builtin_rules() if r.rule_id == "credential_jwt")
    assert (rule.id, rule.name, rule.enabled, rule.severity) == ("company-id", "Company JWT", 0, "critical")
    assert migrations.validate()


def test_mysql_settings_visible_to_another_process(security_mysql_engine, monkeypatch):
    import json
    import subprocess
    import sys

    migrations.apply_migrations()
    repo = repository(monkeypatch, security_mysql_engine)
    repo.initialize_settings()
    repo.update_settings({"mode": "audit", "redact_secrets": True})
    url = security_mysql_engine.url
    env = {**os.environ, "DB_NAME": url.database, "DB_USER": url.username or "root", "DB_PASSWORD": url.password or "",
           "DB_HOST": url.host or "127.0.0.1", "DB_PORT": str(url.port or 3306), "DB_UNIX_SOCKET": url.query.get("unix_socket", "")}
    code = "from dataclasses import asdict; import json; from app.infrastructure.repositories.security_repo import SecurityRepository; print(json.dumps(asdict(SecurityRepository().get_settings())))"
    result = subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["redact_secrets"] is True
