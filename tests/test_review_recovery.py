"""Failure injection for REVIEW-007/008/009 with real transactions."""
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from test_kb_repository import _repository

from app.application.services import kb_worker
from app.application.services.quota_recovery import (
    QuotaRecoveryWorker,
    RecoverableQuota,
)
from app.domain.entities import (
    KbChunkEntity,
    KbDocumentEntity,
    KbKnowledgeBaseEntity,
    KbTaskEntity,
)
from app.domain.task_lease import LostTaskLease, TaskLease
from app.infrastructure.database.connection import row_lock_suffix


def seed(repo):
    repo.save_kb(KbKnowledgeBaseEntity(id="kb", name="docs", doc_count=1, chunk_count=1, total_tokens=7, index_status="ready"))
    repo.save_doc(KbDocumentEntity(id="doc", kb_id="kb", name="test.txt", status="ready", chunk_count=1, total_tokens=7))
    repo.save_chunk(KbChunkEntity(id="old", kb_id="kb", doc_id="doc", content="previous", token_count=7))
    repo.save_task(KbTaskEntity(id="task", kb_id="kb", doc_id="doc", task_type="import"))
    assert repo.claim_next_task("A", 60)
    return TaskLease("A", 1)


def test_row_locks_resolve_the_real_orm_session_dialect():
    # No connection is opened: exercise the production ORM path, rather than
    # only the Core connection used by many MySQL test fixtures.
    engine = create_engine("mysql+pymysql://localhost/unused")
    try:
        with Session(engine) as session:
            assert row_lock_suffix(session) == " FOR UPDATE"
        assert row_lock_suffix(SimpleNamespace(engine=engine)) == " FOR UPDATE"
        assert row_lock_suffix(SimpleNamespace()) == ""
    finally:
        engine.dispose()


def chunks():
    return [KbChunkEntity(id="new", kb_id="kb", doc_id="doc", content="new", token_count=3)]


@pytest.mark.parametrize("boundary", ["INSERT INTO kb_chunks", "UPDATE kb_documents", "UPDATE kb_knowledge_bases", "UPDATE kb_tasks SET status='completed'", "COMMIT"])
def test_publish_rollback_and_retry_are_atomic(monkeypatch, tmp_path, boundary):
    repo, engine = _repository(monkeypatch, tmp_path)
    lease = seed(repo)
    fired = False
    def fail_statement(connection, cursor, statement, params, context, many):
        nonlocal fired
        if not fired and boundary in statement:
            fired = True
            raise RuntimeError("injected transaction failure")
    def fail_commit(connection):
        nonlocal fired
        if not fired:
            fired = True
            raise RuntimeError("injected transaction failure")
    event_name, listener = ("commit", fail_commit) if boundary == "COMMIT" else ("before_cursor_execute", fail_statement)
    event.listen(engine, event_name, listener)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            repo.publish_document("task", lease, "kb", "doc", chunks())
    finally:
        event.remove(engine, event_name, listener)
    assert fired
    assert [(c.id, c.content) for c in repo.find_chunk_by_doc_id("doc")] == [("old", "previous")]
    assert repo.find_doc_by_id("doc").total_tokens == 7
    assert repo.find_task_by_id("task").status == "running"
    assert repo.find_kb_by_id("kb").index_status == "ready"
    assert repo.fail_or_retry_task("task", "retry", 3, lease)
    claim = repo.claim_next_task("B", 60)
    current = TaskLease("B", claim["attempt_count"])
    repo.publish_document("task", current, "kb", "doc", chunks())
    assert [c.id for c in repo.find_chunk_by_doc_id("doc")] == ["new"]
    kb = repo.find_kb_by_id("kb")
    assert (kb.doc_count, kb.chunk_count, kb.total_tokens, kb.index_status) == (1, 1, 3, "stale")
    assert repo.find_task_by_id("task").status == "completed"
    with pytest.raises(LostTaskLease):
        repo.publish_document("task", current, "kb", "doc", chunks())
    engine.dispose()


def test_lease_transfer_fences_every_late_write(monkeypatch, tmp_path):
    repo, engine = _repository(monkeypatch, tmp_path)
    old = seed(repo)
    with engine.begin() as db:
        db.execute(text("UPDATE kb_tasks SET lease_until='2000-01-01' WHERE id='task'"))
    assert not repo.renew_task_lease("task", old, 60)
    repo.recover_expired_tasks()
    claim = repo.claim_next_task("B", 60)
    current = TaskLease("B", claim["attempt_count"])
    assert current.generation == 2
    assert not repo.renew_task_lease("task", old, 60)
    assert not repo.fail_or_retry_task("task", "late failure", 1, old)
    assert not repo.update_task_status("task", "completed", None)
    with pytest.raises(LostTaskLease):
        repo.update_task_progress("task", 99, 100, old)
    with pytest.raises(LostTaskLease):
        repo.publish_document("task", old, "kb", "doc", chunks())
    assert [c.id for c in repo.find_chunk_by_doc_id("doc")] == ["old"]
    assert repo.find_task_by_id("task").worker_id == "B"
    repo.publish_document("task", current, "kb", "doc", chunks())
    assert not repo.fail_or_retry_task("task", "late failure", 1, old)
    assert repo.find_task_by_id("task").status == "completed"
    assert repo.find_doc_by_id("doc").status == "ready"
    engine.dispose()


def test_cancelled_or_mismatched_execution_cannot_replace_prior_version(monkeypatch, tmp_path):
    repo, engine = _repository(monkeypatch, tmp_path)
    lease = seed(repo)
    with pytest.raises(LostTaskLease):
        repo.publish_document("task", lease, "kb", "other", chunks())
    bad = chunks()
    bad[0].kb_id = "other"
    with pytest.raises(ValueError, match="Chunk document"):
        repo.publish_document("task", lease, "kb", "doc", bad)
    lease.cancelled.set()
    with pytest.raises(LostTaskLease):
        repo.publish_document("task", lease, "kb", "doc", chunks())
    assert [c.id for c in repo.find_chunk_by_doc_id("doc")] == ["old"]
    assert repo.fail_or_retry_task("task", "embedding failed", 1, TaskLease("A", 1))
    assert repo.find_doc_by_id("doc").status == "ready"
    engine.dispose()


@pytest.mark.asyncio
async def test_worker_cancellation_stops_late_thread_publication():
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    leases = []
    def run(*args, lease):
        leases.append(lease)
        entered.set()
        try:
            assert release.wait(3)
            lease.check()
            pytest.fail("cancelled thread must not publish")
        finally:
            completed.set()
    repository = Mock()
    worker = kb_worker.KnowledgeTaskWorker(SimpleNamespace(run_import_pipeline=run), repository)
    task = {"id": "t", "worker_id": "A", "attempt_count": 1, "task_type": "import", "kb_id": "kb", "doc_id": "doc", "payload": {"filename": "test.txt", "content": "text"}}
    active = asyncio.create_task(worker._execute_async(task))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
        assert leases[0].cancelled.is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(completed.wait, 2)
    repository.fail_or_retry_task.assert_not_called()


class QuotaLedger:
    """Durable-store stand-in: restart wrappers share this ledger."""
    def __init__(self):
        self.used = 0
        self.status = "reserved"
        self.actual = 0
        self.fail = False
        self.id = "a" * 32
    def reserve(self, *args):
        self.used += args[-1]
        return self.id
    def settle(self, reservation, tokens):
        if self.fail:
            raise OSError("database unavailable")
        if self.status != "reserved":
            return False
        self.actual, self.used, self.status = tokens, tokens, "settled"
        return True
    def release(self, reservation):
        if self.fail:
            raise OSError("database unavailable")
        if self.status != "reserved":
            return False
        self.used, self.status = 0, "released"
        return True
    def outcome_matches(self, reservation, action, tokens):
        return self.status == "released" if action == "release" else self.status == "settled" and self.actual == tokens


@pytest.mark.parametrize("action,tokens", [("settle", 17), ("release", 0)])
def test_settlement_failure_survives_restart_and_replay_is_idempotent(tmp_path, action, tokens):
    ledger = QuotaLedger()
    quota = RecoverableQuota(ledger, tmp_path)
    reservation = quota.reserve("k", "execution", 100)
    assert ledger.used == 100
    ledger.fail = True
    result = quota.settle(reservation, tokens) if action == "settle" else quota.release(reservation)
    assert result is False
    assert RecoverableQuota(ledger, tmp_path).recover()["pending"] == 1
    ledger.fail = False
    restarted = RecoverableQuota(ledger, tmp_path)
    assert restarted.recover()["recovered"] == 1
    assert ledger.used == tokens
    assert restarted.recover()["recovered"] == 0
    assert not list(tmp_path.glob("*.json"))
    # Simulate a crash after DB commit but before outbox acknowledgement.
    restarted._write(reservation, action, tokens)
    assert restarted.recover()["recovered"] == 1
    assert ledger.used == tokens


def test_unknown_consumption_is_retained_and_conflicts_are_visible(tmp_path, caplog):
    ledger = QuotaLedger()
    quota = RecoverableQuota(ledger, tmp_path)
    reservation = quota.reserve("k", "request", 100)
    assert quota.recover()["unknown"] == 1
    assert ledger.used == 100  # Never refund unknown upstream consumption.
    ledger.status, ledger.actual = "settled", 25
    quota._write(reservation, "settle", 99)
    assert quota.recover()["pending"] == 1
    assert "conflict" in caplog.text
    assert (tmp_path / f"{reservation}.json").exists()


@pytest.mark.parametrize("content", ['not-json', '[]', '{"id":"../outside","action":"release","tokens":0}', '{"id":"' + 'a' * 32 + '","action":"unknown-action","tokens":0}', '{"id":"' + 'a' * 32 + '","action":"settle","tokens":-1}'])
def test_invalid_recovery_records_never_execute(tmp_path, content):
    repository = Mock()
    (tmp_path / ("a" * 32 + ".json")).write_text(content)
    assert RecoverableQuota(repository, tmp_path).recover()["invalid"] == 1
    repository.settle.assert_not_called()
    repository.release.assert_not_called()


def test_outbox_write_failure_releases_before_dispatch(monkeypatch, tmp_path):
    ledger = QuotaLedger()
    quota = RecoverableQuota(ledger, tmp_path)
    def unavailable(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(quota, "_write", unavailable)
    with pytest.raises(OSError):
        quota.reserve("k", "request", 100)
    assert ledger.used == 0 and ledger.status == "released"


def test_atomic_intent_failure_preserves_prior_unknown_for_reconciliation(monkeypatch, tmp_path):
    ledger = QuotaLedger()
    quota = RecoverableQuota(ledger, tmp_path)
    reservation = quota.reserve("k", "request", 100)
    def unavailable(*args):
        raise OSError("atomic rename unavailable")
    monkeypatch.setattr("app.application.services.quota_recovery.os.replace", unavailable)
    with pytest.raises(OSError, match="atomic rename"):
        quota.settle(reservation, 17)
    assert ledger.status == "reserved" and ledger.used == 100
    assert json.loads((tmp_path / f"{reservation}.json").read_text())["action"] == "unknown"
    assert not list(tmp_path.glob(".quota-*"))


def test_recovery_capacity_rejects_before_reserving(monkeypatch, tmp_path):
    repository = Mock()
    quota = RecoverableQuota(repository, tmp_path)
    monkeypatch.setattr(type(tmp_path), "glob", lambda *args: iter([tmp_path / "a.json"] * 10000))
    with pytest.raises(RuntimeError, match="spool is full"):
        quota.reserve("k", "request", 1)
    repository.reserve.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_worker_retries_and_stops(tmp_path):
    ledger = QuotaLedger()
    quota = RecoverableQuota(ledger, tmp_path)
    quota._write(ledger.id, "settle", 3)
    worker = QuotaRecoveryWorker(quota)
    await worker.start()
    for _ in range(100):
        if ledger.status == "settled":
            break
        await asyncio.sleep(0.01)
    await worker.stop()
    assert worker.task is None and ledger.used == 3
