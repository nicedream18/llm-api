from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.application.errors import ApplicationError
from app.domain.entities import (
    KbChunkEntity,
    KbDocumentEntity,
    KbKnowledgeBaseEntity,
    KbTaskEntity,
)
from app.domain.task_lease import TaskLease
from app.infrastructure.repositories.kb_repo import KbRepository


def _repository(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'knowledge.sqlite'}")

    @event.listens_for(engine, "connect")
    def register_compatibility_functions(connection, _record):
        connection.create_function("NOW", 0, lambda: datetime.now(UTC).isoformat())
        connection.create_function("UTC_TIMESTAMP", 0, lambda: datetime.now(UTC).isoformat())
        connection.create_function("GREATEST", -1, lambda *values: max(values))
        connection.create_function("RAND", 0, lambda: 0.5)

    with engine.begin() as db:
        db.execute(text("""CREATE TABLE kb_knowledge_bases (
            id TEXT PRIMARY KEY, name TEXT, description TEXT, tags TEXT, chunk_size INTEGER,
            chunk_overlap INTEGER, status INTEGER, embedding_model TEXT, embedding_channel_id TEXT,
            embedding_dim INTEGER, doc_count INTEGER, chunk_count INTEGER, total_tokens INTEGER,
            index_status TEXT, created_at TEXT, updated_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE kb_documents (
            id TEXT PRIMARY KEY, kb_id TEXT, name TEXT, source_type TEXT, source_path TEXT,
            status TEXT, chunk_count INTEGER, total_tokens INTEGER, error_message TEXT,
            created_at TEXT, updated_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE kb_chunks (
            id TEXT PRIMARY KEY, doc_id TEXT, kb_id TEXT, content TEXT, chunk_index INTEGER,
            token_count INTEGER, embedding BLOB, chunk_type TEXT, language TEXT, metadata TEXT,
            created_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE kb_tasks (
            id TEXT PRIMARY KEY, kb_id TEXT, doc_id TEXT, task_type TEXT, status TEXT,
            progress INTEGER, total_items INTEGER, done_items INTEGER, error_message TEXT,
            created_at TEXT, payload TEXT, worker_id TEXT, lease_until TEXT,
            attempt_count INTEGER DEFAULT 0, started_at TEXT, completed_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE kb_conversations (
            id TEXT PRIMARY KEY, kb_id TEXT, role TEXT, content TEXT, sources TEXT,
            model TEXT, tokens_used INTEGER, created_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE kb_sources (
            id TEXT PRIMARY KEY, kb_id TEXT, source_type TEXT, source_url TEXT, source_path TEXT,
            branch TEXT, status TEXT, file_count INTEGER, error TEXT, created_at TEXT, updated_at TEXT
        )"""))
        db.execute(text("""CREATE TABLE kb_index_meta (
            kb_id TEXT PRIMARY KEY, index_type TEXT, embedding_dim TEXT, chunk_count TEXT,
            index_path TEXT, built_at TEXT, status TEXT
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

    monkeypatch.setattr("app.infrastructure.repositories.kb_repo.get_db", get_db)
    return KbRepository(), engine


def test_kb_documents_chunks_sources_stats_and_delete_lifecycle(monkeypatch, tmp_path):
    repo, engine = _repository(monkeypatch, tmp_path)
    kb = KbKnowledgeBaseEntity(
        id="kb-1", name="Engineering", description="docs", tags=["team", "python"],
        embedding_model="embed-v1", index_status="ready",
    )
    repo.save_kb(kb)
    assert kb.created_at and kb.updated_at
    assert repo.find_kb_by_id(kb.id).tags == ["team", "python"]
    assert repo.find_kb_by_id("missing") is None
    assert [item.id for item in repo.find_all_kb()] == ["kb-1"]
    kb.name = "Engineering Docs"
    repo.update_kb(kb)
    assert repo.find_kb_by_id(kb.id).name == "Engineering Docs"
    assert repo.set_index_state_if_unchanged(kb.id, kb.updated_at, "building", 768) is True
    assert repo.set_index_state_if_unchanged(kb.id, "stale-version", "ready") is False

    doc = KbDocumentEntity(
        id="doc-1", kb_id=kb.id, name="guide.md", source_type="upload", source_path="guide.md",
        status="ready", chunk_count=2, total_tokens=42,
    )
    repo.save_doc(doc)
    repo.save_doc(KbDocumentEntity(
        id="doc-2", kb_id=kb.id, name="draft.md", status="pending",
    ))
    assert doc.created_at and doc.updated_at
    assert repo.find_doc_by_id("doc-1").total_tokens == 42
    assert repo.find_doc_by_id("missing") is None
    assert {item.id for item in repo.find_doc_by_kb_id(kb.id)} == {"doc-1", "doc-2"}
    doc.error_message = "reprocessed"
    doc.updated_at = None
    repo.update_doc(doc)
    repo.update_doc_status("doc-2", "error", "parser failed")
    assert repo.find_doc_by_id("doc-1").error_message == "reprocessed"
    assert repo.find_doc_by_id("doc-2").status == "error"

    chunks = [
        KbChunkEntity(id="chunk-2", doc_id=doc.id, kb_id=kb.id, content="second", chunk_index=2, token_count=12, embedding=b"\x00\x01", metadata='{"h":2}'),
        KbChunkEntity(doc_id=doc.id, kb_id=kb.id, content="first", chunk_index=1, token_count=30, chunk_type="text", language="en"),
    ]
    repo.save_chunk_batch([])
    repo.save_chunk_batch(chunks)
    repo.save_chunk(KbChunkEntity(id="chunk-3", doc_id="doc-2", kb_id=kb.id, content="other", chunk_index=3))
    found_chunks = repo.find_chunk_by_doc_id(doc.id)
    assert [item.chunk_index for item in found_chunks] == [1, 2]
    assert found_chunks[1].embedding == b"\x00\x01"
    assert found_chunks[1].metadata == '{"h":2}'
    assert len(repo.find_chunk_by_kb_id(kb.id)) == 3
    repo.update_chunk_embedding("chunk-2", b"new")
    assert repo.find_chunk_by_doc_id(doc.id)[1].embedding == b"new"
    assert len(repo.sample_contents(kb.id, 2)) == 2

    repo.save_conversation(kb.id, "user", "question", model="gpt", tokens_used=4)
    repo.save_conversation(kb.id, "assistant", "answer", sources="[]", model="gpt", tokens_used=7)
    assert repo.count_conversations(kb.id) == 2
    assert [item["role"] for item in repo.find_conversation_by_kb_id(kb.id)] == ["user", "assistant"]
    stats = repo.get_kb_stats(kb.id)
    assert (stats.doc_count, stats.chunk_count, stats.total_tokens, stats.conversation_count) == (2, 3, 42, 2)
    assert stats.index_status == "building"
    assert repo.get_kb_stats("missing") is None
    assert repo.clear_conversations(kb.id) is True
    assert repo.count_conversations(kb.id) == 0

    source = repo.save_source(kb.id, "git", source_url="https://example.test/repo", branch="main", file_count=3)
    assert repo.update_source_status(source, "ingested", file_count=4) is True
    assert repo.update_source_status("missing", "failed") is False
    assert repo.find_source_by_id(source)["file_count"] == 4
    assert repo.find_sources_by_kb_id(kb.id)[0]["status"] == "ingested"
    assert repo.find_source_by_id("missing") is None
    assert repo.delete_source(source) is True
    assert repo.delete_source(source) is False

    repo.upsert_index_meta(kb.id, "unknown", "ignored")
    assert repo.find_index_meta_by_kb_id(kb.id) == {}
    repo.upsert_index_meta(kb.id, "index_type", "hnsw")
    repo.upsert_index_meta(kb.id, "status", "ready")
    assert repo.find_index_meta_by_kb_id(kb.id)["index_type"] == "hnsw"
    assert repo.find_index_meta_by_kb_id(kb.id)["status"] == "ready"

    assert repo.delete_doc_by_id("missing") is False
    with engine.begin() as db:
        db.execute(text("UPDATE kb_knowledge_bases SET index_status='ready' WHERE id=:kb"), {"kb": kb.id})
        db.execute(text("""INSERT INTO kb_tasks (id, kb_id, doc_id, task_type, status, created_at)
            VALUES ('running-doc-task', :kb, 'doc-1', 'reindex', 'running', 'a')"""), {"kb": kb.id})
    with pytest.raises(ApplicationError, match="running task"):
        repo.delete_doc_by_id("doc-1")
    with engine.begin() as db:
        db.execute(text("DELETE FROM kb_tasks WHERE id='running-doc-task'"))
        db.execute(text("""INSERT INTO kb_tasks (id, kb_id, doc_id, task_type, status, created_at)
            VALUES ('pending-doc-task', :kb, 'doc-1', 'reindex', 'pending', 'a')"""), {"kb": kb.id})
    assert repo.delete_doc_by_id("doc-1") is True
    assert repo.find_doc_by_id("doc-1") is None
    assert repo.find_kb_by_id(kb.id).index_status == "stale"

    assert repo.delete_kb_by_id("missing") is False
    with engine.begin() as db:
        db.execute(text("UPDATE kb_tasks SET status='running' WHERE id='pending-doc-task'"))
    with pytest.raises(ApplicationError, match="running tasks"):
        repo.delete_kb_by_id(kb.id)
    with engine.begin() as db:
        db.execute(text("DELETE FROM kb_tasks WHERE kb_id=:kb"), {"kb": kb.id})
    assert repo.delete_kb_by_id(kb.id) is True
    assert repo.find_all_kb() == []
    engine.dispose()


def test_kb_task_claim_lease_retry_and_terminal_updates(monkeypatch, tmp_path):
    repo, engine = _repository(monkeypatch, tmp_path)
    repo.save_kb(KbKnowledgeBaseEntity(id="kb-task", name="Tasks"))
    repo.save_doc(KbDocumentEntity(id="doc-task", kb_id="kb-task", name="source.md"))
    repo.save_task(KbTaskEntity(
        id="task-import", kb_id="kb-task", doc_id="doc-task", task_type="import",
        total_items=2,
    ), {"filename": "source.md", "content": "hello"})
    claimed = repo.claim_next_task("worker-1", 60)
    assert claimed["id"] == "task-import" and claimed["payload"]["filename"] == "source.md"
    assert repo.claim_next_task("worker-2", 60) is None
    task = repo.find_task_by_id("task-import")
    assert task.status == "running" and task.worker_id == "worker-1" and task.attempt_count == 1
    assert repo.renew_task_lease("task-import", TaskLease("worker-1", 1), 60) is True
    assert repo.renew_task_lease("task-import", TaskLease("worker-2", 1), 60) is False
    repo.update_task_progress("task-import", 1, 50, TaskLease("worker-1", 1))
    repo.recover_expired_tasks()
    assert repo.find_task_by_id("task-import").status == "running"
    with engine.begin() as db:
        db.execute(text("UPDATE kb_tasks SET lease_until='2000-01-01 00:00:00' WHERE id='task-import'"))
    repo.recover_expired_tasks()
    assert repo.find_task_by_id("task-import").status == "pending"
    assert repo.find_task_by_id("task-import").worker_id is None

    assert repo.claim_next_task("worker-1", 60)
    assert repo.fail_or_retry_task("task-import", "temporary", 3, TaskLease("worker-1", 2)) is True
    assert repo.find_task_by_id("task-import").status == "pending"
    with engine.begin() as db:
        db.execute(text("UPDATE kb_tasks SET attempt_count=2 WHERE id='task-import'"))
    assert repo.claim_next_task("worker-1", 60)
    assert repo.fail_or_retry_task("task-import", "permanent", 2, TaskLease("worker-1", 3)) is True
    failed = repo.find_task_by_id("task-import")
    assert failed.status == "failed" and failed.completed_at
    assert repo.find_doc_by_id("doc-task").status == "error"
    assert repo.fail_or_retry_task("missing", "error", 2, TaskLease("worker-1", 1)) is False
    assert repo.cancel_task("kb-task", "task-import") is False
    assert repo.update_task_status("task-import", "completed", None) is False
    assert repo.find_task_by_id("task-import").status == "failed"

    repo.save_task(KbTaskEntity(id="task-cancel", kb_id="kb-task", task_type="reindex"))
    assert repo.cancel_task("other-kb", "task-cancel") is False
    assert repo.cancel_task("kb-task", "task-cancel") is True
    repo.update_task_status("task-cancel", "running", None)
    assert repo.find_task_by_id("task-cancel").status == "cancelled"
    assert repo.save_task_payload("task-cancel", {"updated": True}) is True
    assert repo.save_task_payload("missing", {}) is False

    with engine.begin() as db:
        db.execute(text("""INSERT INTO kb_tasks (id, kb_id, doc_id, task_type, status, created_at)
            VALUES ('orphan', 'missing-kb', NULL, 'import', 'pending', 'a')"""))
        db.execute(text("UPDATE kb_tasks SET payload=:bad WHERE id='task-cancel'"), {"bad": "not-json"})
    assert repo.claim_next_task("worker-3", 60) is None
    with engine.begin() as db:
        db.execute(text("DELETE FROM kb_tasks WHERE id='orphan'"))
        db.execute(text("UPDATE kb_tasks SET status='pending', doc_id='missing-doc' WHERE id='task-cancel'"))
    assert repo.claim_next_task("worker-3", 60) is None
    assert repo.find_task_by_id("task-cancel").status == "cancelled"
    engine.dispose()
