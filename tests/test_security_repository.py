from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.entities import SecurityCustomRuleEntity, SecurityFindingEntity
from app.infrastructure.repositories.security_repo import SecurityRepository


def _repository(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as db:
        db.execute(text("""CREATE TABLE security_findings (
            id TEXT PRIMARY KEY, log_id TEXT, phase TEXT, category TEXT, rule_id TEXT,
            severity TEXT, title TEXT, description TEXT, location TEXT, evidence_masked TEXT,
            evidence_hash TEXT, action TEXT, created_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE security_builtin_rules (
            id TEXT PRIMARY KEY, category TEXT, rule_id TEXT, name TEXT, title TEXT,
            description TEXT, severity TEXT, pattern TEXT, action TEXT, enabled INTEGER,
            created_at TEXT, updated_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE security_custom_rules (
            id TEXT PRIMARY KEY, category TEXT, name TEXT, description TEXT,
            severity TEXT, pattern TEXT, action TEXT, enabled INTEGER,
            created_at TEXT, updated_at TEXT
        )"""))
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def get_db():
        session = sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("app.infrastructure.repositories.security_repo.get_db", get_db)
    return SecurityRepository(), engine


def test_security_findings_and_rules_persist_and_update(monkeypatch):
    repo, engine = _repository(monkeypatch)
    repo.save_findings([])
    finding = SecurityFindingEntity(
        id="finding-1", log_id="log-1", phase="request", category="secret",
        rule_id="credential", severity="high", title="Credential detected",
        description="masked", location="messages[0]", evidence_masked="sk-***",
        evidence_hash="hash", action="block",
    )
    repo.save_findings([finding])
    assert finding.created_at and finding.id == "finding-1"
    assert repo.count_findings() == 1
    assert repo.get_findings_by_log_id("log-1")[0] == finding
    assert repo.get_all_findings(0, 10)[0].evidence_hash == "hash"

    with engine.begin() as db:
        db.execute(text("""INSERT INTO security_builtin_rules
            (id, category, rule_id, name, title, description, severity, pattern, action, enabled, created_at, updated_at)
            VALUES ('builtin-1', 'secret', 'credential', 'Credential', 'Fallback', 'description', 'high', 'secret', 'block', 1, 'a', 'a')"""))
    builtin = repo.get_all_builtin_rules()[0]
    assert (builtin.id, builtin.name, builtin.enabled) == ("builtin-1", "Credential", 1)
    assert repo.update_builtin_rule("builtin-1", None, None) is False
    assert repo.update_builtin_rule("builtin-1", 0, "critical") is True
    assert repo.update_builtin_rule("missing", 1, None) is False
    assert repo.get_all_builtin_rules()[0].severity == "critical"

    custom = repo.create_custom_rule(SecurityCustomRuleEntity(
        category="keyword", name="custom", pattern="private", severity="medium",
        action="redact", enabled=1,
    ))
    assert custom.id and custom.updated_at and custom.created_at
    assert repo.get_all_custom_rules()[0].name == "custom"
    custom.description = "updated"
    custom.enabled = 0
    assert repo.update_custom_rule(custom) is True
    assert repo.get_all_custom_rules()[0].description == "updated"
    assert repo.update_custom_rule(SecurityCustomRuleEntity(id="missing", name="none")) is False
    assert repo.delete_custom_rule(custom.id) is True
    assert repo.delete_custom_rule(custom.id) is False
    engine.dispose()
