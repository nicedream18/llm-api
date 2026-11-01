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
