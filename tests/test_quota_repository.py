from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.application.services.quota_recovery import RecoverableQuota
from app.infrastructure.repositories.quota_repo import QuotaRepository


class FakeResult:
    rowcount = 1

class FakeDB:
    def __init__(self, rows=None):
        self.statements=[]
        self.rows=rows or []
    def execute(self, query, params=None):
        self.statements.append((str(query), params or {}))
        class Result(FakeResult):
            def mappings(inner): return inner
            def first(inner): return self.rows.pop(0) if self.rows else None
        return Result()

class Context:
    def __init__(self, db): self.db=db
    def __enter__(self): return self.db
    def __exit__(self, *args): return False

def test_reserve_is_atomic_update_before_ledger(monkeypatch):
    db=FakeDB()
    monkeypatch.setattr('app.infrastructure.repositories.quota_repo.get_db', lambda: Context(db))
    repo=QuotaRepository()
    result=repo.reserve('key-id','req-id',7)
    assert result
    update_index = next(i for i, (sql, _) in enumerate(db.statements) if 'UPDATE api_keys SET quota_used=quota_used+' in sql)
    ledger_index = next(i for i, (sql, _) in enumerate(db.statements) if 'INSERT INTO api_key_quota_ledger' in sql)
    assert update_index < ledger_index


def test_quota_reservation_idempotency_settlement_and_release(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'quota.sqlite'}")

    @event.listens_for(engine, "connect")
    def register_greatest(connection, _record):
        connection.create_function("GREATEST", -1, lambda *values: max(values))

    with engine.begin() as db:
        db.execute(text("CREATE TABLE api_keys (id TEXT PRIMARY KEY, status INTEGER, quota_limit INTEGER, quota_used INTEGER, updated_at TEXT)"))
        db.execute(text("""CREATE TABLE api_key_quota_ledger (
            id TEXT PRIMARY KEY, api_key_id TEXT, request_id TEXT UNIQUE, reserved_tokens INTEGER,
            actual_tokens INTEGER, released_tokens INTEGER, status TEXT, created_at TEXT, settled_at TEXT
        )"""))
        db.execute(text("INSERT INTO api_keys VALUES ('key-a', 1, 100, 0, NULL), ('key-disabled', 0, 0, 0, NULL)"))
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

    monkeypatch.setattr("app.infrastructure.repositories.quota_repo.get_db", get_db)
    repo = QuotaRepository()

    first = repo.reserve("key-a", "request-a", 50)
    assert first is not None
    assert repo.reserve("key-a", "request-a", 50) == first
    assert repo.reserve("key-disabled", "request-a", 50) is None
    assert repo.reserve("key-a", "request-denied", 60) is None
    assert repo.reserve("key-disabled", "request-disabled", 1) is None
    assert repo.reserve("key-a", "request-negative", -5) is not None
    assert repo.settle(first, 20) is True
    assert repo.settle(first, 20) is False
    assert repo.outcome_matches(first, "settle", 20)
    assert not repo.outcome_matches(first, "settle", 19)
    assert not repo.outcome_matches(first, "release", 0)
    assert not repo.outcome_matches("missing", "settle", 1)
    with engine.connect() as db:
        assert db.execute(text("SELECT quota_used FROM api_keys WHERE id='key-a'")).scalar_one() == 20
        ledger = db.execute(text("SELECT actual_tokens, released_tokens, status FROM api_key_quota_ledger WHERE id=:id"), {"id": first}).one()
        assert tuple(ledger) == (20, 30, "settled")
    assert repo.reserve("key-a", "request-a", 10) is None
    assert repo.settle("missing", 1) is False

    released = repo.reserve("key-a", "request-release", 10)
    oversize = repo.reserve("key-a", "request-oversize", 70)
    assert oversize is not None
    assert repo.settle(oversize, 150) is True
    with engine.connect() as db:
        row = db.execute(text("SELECT quota_used FROM api_keys WHERE id='key-a'")).scalar_one()
        settled = db.execute(text("SELECT actual_tokens, released_tokens FROM api_key_quota_ledger WHERE id=:id"), {"id": oversize}).one()
        assert row == 180
        assert tuple(settled) == (150, 0)

    assert repo.reserve("key-a", "request-after-debt", 1) is None
    assert released is not None
    assert repo.release(released) is True
    assert repo.outcome_matches(released, "release", 0)
    assert not repo.outcome_matches(released, "settle", 0)
    assert repo.release(released) is False
    assert repo.release("missing") is False
    with engine.connect() as db:
        assert db.execute(text("SELECT quota_used FROM api_keys WHERE id='key-a'")).scalar_one() == 170
        status = db.execute(text("SELECT status, released_tokens FROM api_key_quota_ledger WHERE id=:id"), {"id": released}).one()
        assert tuple(status) == ("released", 10)

    # Exercise the durable spool with the real transactional repository. A lost
    # DB connection after the upstream response is retried by a new wrapper.
    with engine.begin() as db:
        db.execute(text("INSERT INTO api_keys VALUES ('key-recovery', 1, 100, 0, NULL)"))
    spool = tmp_path / "recovery"
    durable = RecoverableQuota(repo, spool)
    reservation = durable.reserve("key-recovery", "request-recovery", 50)
    assert reservation is not None
    original = repo.settle
    def unavailable(*args):
        raise OSError("database offline")
    monkeypatch.setattr(repo, "settle", unavailable)
    assert durable.settle(reservation, 7) is False
    with engine.connect() as db:
        assert db.execute(text("SELECT status FROM api_key_quota_ledger WHERE id=:id"), {"id": reservation}).scalar_one() == "reserved"
    monkeypatch.setattr(repo, "settle", original)
    recovered = RecoverableQuota(QuotaRepository(), spool)
    assert recovered.recover()["recovered"] == 1
    assert recovered.recover()["recovered"] == 0
    with engine.connect() as db:
        assert db.execute(text("SELECT quota_used FROM api_keys WHERE id='key-recovery'")).scalar_one() == 7
    engine.dispose()
