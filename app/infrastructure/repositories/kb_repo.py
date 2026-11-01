"""Knowledge base repository for KB, documents, chunks, tasks, conversations, sources."""
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.config import config
from app.domain.entities import (
    KbChunkEntity,
    KbDocumentEntity,
    KbKnowledgeBaseEntity,
    KbStatsEntity,
    KbTaskEntity,
)
from app.infrastructure.database.connection import get_db

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class KbRepository:

    # ---- KnowledgeBase ----

    def save_kb(self, entity: KbKnowledgeBaseEntity):
        if not entity.id:
            entity.id = str(uuid.uuid4())
        now = _now()
        if not entity.created_at:
            entity.created_at = now
        if not entity.updated_at:
            entity.updated_at = now
        if entity.status is None:
            entity.status = 1
        if not entity.index_status:
            entity.index_status = "none"
        with get_db() as db:
            db.execute(text(
                "INSERT INTO kb_knowledge_bases (id, name, description, tags, chunk_size, chunk_overlap, status, "
                "embedding_model, embedding_channel_id, embedding_dim, doc_count, chunk_count, total_tokens, "
                "index_status, created_at, updated_at) "
                "VALUES (:id, :name, :description, :tags, :chunk_size, :chunk_overlap, :status, "
                ":embedding_model, :embedding_channel_id, :embedding_dim, :doc_count, :chunk_count, :total_tokens, "
                ":index_status, :created_at, :updated_at)"
            ), self._kb_params(entity))

    def find_kb_by_id(self, kb_id: str) -> KbKnowledgeBaseEntity | None:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, name, description, tags, chunk_size, chunk_overlap, status, "
                "embedding_model, embedding_channel_id, embedding_dim, doc_count, chunk_count, total_tokens, "
                "index_status, created_at, updated_at FROM kb_knowledge_bases WHERE id = :id"
            ), {"id": kb_id}).mappings().first()
            return self._to_kb_entity(row) if row else None

    def find_all_kb(self) -> list[KbKnowledgeBaseEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, name, description, tags, chunk_size, chunk_overlap, status, "
                "embedding_model, embedding_channel_id, embedding_dim, doc_count, chunk_count, total_tokens, "
                "index_status, created_at, updated_at FROM kb_knowledge_bases ORDER BY created_at DESC"
            )).mappings().all()
            return [self._to_kb_entity(r) for r in rows]

    def update_kb(self, entity: KbKnowledgeBaseEntity):
        entity.updated_at = _now()
        with get_db() as db:
            db.execute(text(
                "UPDATE kb_knowledge_bases SET name=:name, description=:description, tags=:tags, "
                "chunk_size=:chunk_size, chunk_overlap=:chunk_overlap, status=:status, "
                "embedding_model=:embedding_model, embedding_channel_id=:embedding_channel_id, "
                "embedding_dim=:embedding_dim, doc_count=:doc_count, chunk_count=:chunk_count, total_tokens=:total_tokens, index_status=:index_status, updated_at=:updated_at WHERE id=:id"
            ), self._kb_params(entity))

    def delete_kb_by_id(self, kb_id: str):
        with get_db() as db:
            db.execute(text("DELETE FROM kb_chunks WHERE kb_id = :id"), {"id": kb_id})
            db.execute(text("DELETE FROM kb_documents WHERE kb_id = :id"), {"id": kb_id})
            db.execute(text("DELETE FROM kb_conversations WHERE kb_id = :id"), {"id": kb_id})
            db.execute(text("DELETE FROM kb_knowledge_bases WHERE id = :id"), {"id": kb_id})

    # ---- Document ----

    def save_doc(self, entity: KbDocumentEntity):
        if not entity.id:
            entity.id = str(uuid.uuid4())
        now = _now()
        if not entity.created_at:
            entity.created_at = now
        if not entity.updated_at:
            entity.updated_at = now
        with get_db() as db:
            db.execute(text(
                "INSERT INTO kb_documents (id, kb_id, name, source_type, source_path, status, "
                "chunk_count, total_tokens, error_message, created_at, updated_at) "
                "VALUES (:id, :kb_id, :name, :source_type, :source_path, :status, "
                ":chunk_count, :total_tokens, :error_message, :created_at, :updated_at)"
            ), self._doc_params(entity))

    def update_doc(self, entity: KbDocumentEntity):
        if not entity.updated_at:
            entity.updated_at = _now()
        with get_db() as db:
            db.execute(text(
                "UPDATE kb_documents SET name=:name, source_type=:source_type, source_path=:source_path, "
                "status=:status, chunk_count=:chunk_count, total_tokens=:total_tokens, "
                "error_message=:error_message, updated_at=:updated_at WHERE id=:id"
            ), self._doc_params(entity))

    def find_doc_by_id(self, doc_id: str) -> KbDocumentEntity | None:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, kb_id, name, source_type, source_path, status, chunk_count, total_tokens, "
                "error_message, created_at, updated_at FROM kb_documents WHERE id = :id"
            ), {"id": doc_id}).mappings().first()
            return self._to_doc_entity(row) if row else None

    def find_doc_by_kb_id(self, kb_id: str) -> list[KbDocumentEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, kb_id, name, source_type, source_path, status, chunk_count, total_tokens, "
                "error_message, created_at, updated_at FROM kb_documents WHERE kb_id = :kb_id ORDER BY created_at DESC"
            ), {"kb_id": kb_id}).mappings().all()
            return [self._to_doc_entity(r) for r in rows]

    def delete_doc_by_id(self, doc_id: str):
        with get_db() as db:
            db.execute(text("DELETE FROM kb_chunks WHERE doc_id = :id"), {"id": doc_id})
            db.execute(text("DELETE FROM kb_documents WHERE id = :id"), {"id": doc_id})

    def update_doc_status(self, doc_id: str, status: str, error_message: str | None):
        with get_db() as db:
            db.execute(text(
                "UPDATE kb_documents SET status=:status, error_message=:error_message, updated_at=NOW() WHERE id=:id"
            ), {"id": doc_id, "status": status, "error_message": error_message})

    # ---- Chunk ----

    def save_chunk(self, entity: KbChunkEntity):
        if not entity.id:
            entity.id = str(uuid.uuid4())
        if not entity.created_at:
            entity.created_at = _now()
        with get_db() as db:
            db.execute(text(
                "INSERT INTO kb_chunks (id, doc_id, kb_id, content, chunk_index, token_count, embedding, "
                "chunk_type, language, metadata, created_at) "
                "VALUES (:id, :doc_id, :kb_id, :content, :chunk_index, :token_count, :embedding, "
                ":chunk_type, :language, :metadata, :created_at)"
            ), self._chunk_params(entity))

    def save_chunk_batch(self, entities: list[KbChunkEntity]):
        if not entities:
            return
        with get_db() as db:
            for e in entities:
                if not e.id:
                    e.id = str(uuid.uuid4())
                if not e.created_at:
                    e.created_at = _now()
                db.execute(text(
                    "INSERT INTO kb_chunks (id, doc_id, kb_id, content, chunk_index, token_count, embedding, "
                    "chunk_type, language, metadata, created_at) "
                    "VALUES (:id, :doc_id, :kb_id, :content, :chunk_index, :token_count, :embedding, "
                    ":chunk_type, :language, :metadata, :created_at)"
                ), self._chunk_params(e))

    def find_chunk_by_kb_id(self, kb_id: str) -> list[KbChunkEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, doc_id, kb_id, content, chunk_index, token_count, embedding, "
                "chunk_type, language, metadata, created_at FROM kb_chunks WHERE kb_id = :kb_id ORDER BY chunk_index ASC"
            ), {"kb_id": kb_id}).mappings().all()
            return [self._to_chunk_entity(r) for r in rows]

    def find_chunk_by_doc_id(self, doc_id: str) -> list[KbChunkEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, doc_id, kb_id, content, chunk_index, token_count, embedding, "
                "chunk_type, language, metadata, created_at FROM kb_chunks WHERE doc_id = :doc_id ORDER BY chunk_index ASC"
            ), {"doc_id": doc_id}).mappings().all()
            return [self._to_chunk_entity(r) for r in rows]

    def update_chunk_embedding(self, chunk_id: str, embedding: bytes):
        with get_db() as db:
            db.execute(text("UPDATE kb_chunks SET embedding = :embedding WHERE id = :id"),
                       {"id": chunk_id, "embedding": embedding})

    def fulltext_search(self, kb_id: str, query: str, limit: int) -> list[KbChunkEntity]:
        import re
        safe_query = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff\s+*]', '', query).strip()
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, doc_id, kb_id, content, chunk_index, token_count, embedding, "
                "chunk_type, language, metadata, created_at FROM kb_chunks "
                f"WHERE kb_id = :kb_id AND MATCH(content) AGAINST('{safe_query}' IN BOOLEAN MODE) LIMIT :limit"
            ), {"kb_id": kb_id, "limit": limit}).mappings().all()
            return [self._to_chunk_entity(r) for r in rows]

    def sample_contents(self, kb_id: str, limit: int) -> list[str]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT content FROM kb_chunks WHERE kb_id = :kb_id ORDER BY RAND() LIMIT :limit"
            ), {"kb_id": kb_id, "limit": limit}).mappings().all()
            return [r["content"] for r in rows]

    # ---- Task ----

    def save_task(self, entity: KbTaskEntity, payload: dict | None = None):
        if not entity.id:
            entity.id = str(uuid.uuid4())
        if not entity.created_at:
            entity.created_at = _now()
        with get_db() as db:
            db.execute(text("INSERT INTO kb_tasks (id,kb_id,doc_id,task_type,status,progress,total_items,done_items,error_message,created_at,payload) VALUES (:id,:kb_id,:doc_id,:task_type,:status,:progress,:total_items,:done_items,:error_message,:created_at,:payload)"), {**self._task_params(entity), "payload": json.dumps(payload or {})})

    def claim_next_task(self, worker_id: str, lease_seconds: int):
        lease_until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as db:
            task_id = None
            for row in db.execute(text("SELECT id, doc_id FROM kb_tasks WHERE status='pending' AND task_type IN ('import','reindex') ORDER BY created_at ASC LIMIT 50 FOR UPDATE SKIP LOCKED")).mappings().all():
                if row["doc_id"]:
                    active = db.execute(text("SELECT 1 FROM kb_tasks WHERE status='running' AND doc_id=:doc_id LIMIT 1"), {"doc_id": row["doc_id"]}).first()
                    if active:
                        continue
                candidate_id = row["id"]
                updated = db.execute(text("UPDATE kb_tasks SET status='running',worker_id=:worker_id,lease_until=:lease_until,started_at=:started_at,attempt_count=attempt_count+1 WHERE id=:id AND status='pending'"), {"worker_id":worker_id,"lease_until":lease_until,"started_at":_now(),"id":candidate_id})
                if updated.rowcount == 1:
                    task_id = candidate_id
                    break
            if not task_id:
                return None
            task = db.execute(text("SELECT id,kb_id,doc_id,task_type,payload FROM kb_tasks WHERE id=:id"), {"id":task_id}).mappings().first()
            if not task:
                return None
            try:
                payload = json.loads(task["payload"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            return {**dict(task), "payload":payload}

    def renew_task_lease(self, task_id: str, worker_id: str, lease_seconds: int) -> bool:
        lease_until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as db:
            result = db.execute(text("UPDATE kb_tasks SET lease_until=:lease_until WHERE id=:id AND worker_id=:worker_id AND status='running'"),
                                {"lease_until": lease_until, "id": task_id, "worker_id": worker_id})
            return result.rowcount == 1

    def recover_expired_tasks(self):
        with get_db() as db:
            db.execute(text("UPDATE kb_tasks SET status='pending',worker_id=NULL,lease_until=NULL WHERE status='running' AND (lease_until IS NULL OR lease_until < :now)"), {"now":datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")})

    def fail_or_retry_task(self, task_id: str, message: str, max_attempts: int):
        with get_db() as db:
            row=db.execute(text("SELECT attempt_count, doc_id FROM kb_tasks WHERE id=:id FOR UPDATE"), {"id":task_id}).mappings().first()
            if not row:
                return False
            status="failed" if int(row["attempt_count"] or 0)>=max_attempts else "pending"
            db.execute(text("UPDATE kb_tasks SET status=:status,error_message=:error_message,worker_id=NULL,lease_until=NULL,completed_at=CASE WHEN :status='failed' THEN :now ELSE completed_at END WHERE id=:id"), {"id":task_id,"status":status,"error_message":message[:2000],"now":_now()})
            if status == "failed" and row["doc_id"]:
                db.execute(text("UPDATE kb_documents SET status='error',error_message='Knowledge task failed',updated_at=:now WHERE id=:doc_id"), {"now":_now(), "doc_id":row["doc_id"]})
            return True

    def cancel_task(self, kb_id: str, task_id: str) -> bool:
        with get_db() as db:
            result=db.execute(text("UPDATE kb_tasks SET status='cancelled',completed_at=:now WHERE id=:id AND kb_id=:kb_id AND status='pending'"), {"id":task_id,"kb_id":kb_id,"now":_now()})
            return result.rowcount==1

    def find_task_by_id(self, task_id: str) -> KbTaskEntity | None:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, kb_id, doc_id, task_type, status, progress, total_items, done_items, "
                "error_message, created_at, completed_at, payload, worker_id, lease_until, attempt_count, started_at FROM kb_tasks WHERE id = :id"
            ), {"id": task_id}).mappings().first()
            return self._to_task_entity(row) if row else None

    def update_task_status(self, task_id: str, status: str, error_message: str | None):
        with get_db() as db:
            if status in ("completed", "failed", "cancelled"):
                db.execute(text(
                    "UPDATE kb_tasks SET status=:status, error_message=:error_message, completed_at=UTC_TIMESTAMP(), worker_id=NULL, lease_until=NULL WHERE id=:id"
                ), {"id": task_id, "status": status, "error_message": error_message})
            else:
                db.execute(text(
                    "UPDATE kb_tasks SET status=:status, error_message=:error_message WHERE id=:id"
                ), {"id": task_id, "status": status, "error_message": error_message})

    def update_task_progress(self, task_id: str, done_items: int, progress: int):
        lease_until = (datetime.now(UTC) + timedelta(seconds=config.workers.lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as db:
            db.execute(text(
                "UPDATE kb_tasks SET done_items=:done_items, progress=:progress, lease_until=:lease_until WHERE id=:id AND status='running'"
            ), {"id": task_id, "done_items": done_items, "progress": progress, "lease_until": lease_until})

    # ---- Conversation ----

    def save_conversation(self, kb_id: str, role: str, content: str, sources: str | None = None, model: str | None = None, tokens_used: int = 0):
        with get_db() as db:
            db.execute(text(
                "INSERT INTO kb_conversations (id, kb_id, role, content, sources, model, tokens_used, created_at) "
                "VALUES (:id, :kb_id, :role, :content, :sources, :model, :tokens_used, :created_at)"
            ), {
                "id": str(uuid.uuid4()), "kb_id": kb_id, "role": role, "content": content,
                "sources": sources, "model": model, "tokens_used": tokens_used, "created_at": _now(),
            })

    def find_conversation_by_kb_id(self, kb_id: str) -> list[dict]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, kb_id, role, content, sources, model, tokens_used, created_at "
                "FROM kb_conversations WHERE kb_id = :kb_id ORDER BY created_at ASC"
            ), {"kb_id": kb_id}).mappings().all()
            return [{"role": r["role"], "content": r["content"]} for r in rows]

    def clear_conversations(self, kb_id: str) -> bool:
        with get_db() as db:
            db.execute(text("DELETE FROM kb_conversations WHERE kb_id = :kb_id"), {"kb_id": kb_id})
            return True

    def count_conversations(self, kb_id: str) -> int:
        with get_db() as db:
            row = db.execute(text(
                "SELECT COUNT(*) AS cnt FROM kb_conversations WHERE kb_id = :kb_id"
            ), {"kb_id": kb_id}).mappings().first()
            return int(row["cnt"]) if row else 0

    # ---- Stats ----

    def get_kb_stats(self, kb_id: str) -> KbStatsEntity | None:
        with get_db() as db:
            row = db.execute(text(
                "SELECT (SELECT COUNT(*) FROM kb_documents WHERE kb_id = :kb_id) AS doc_count, "
                "(SELECT COALESCE(SUM(total_tokens), 0) FROM kb_documents WHERE kb_id = :kb_id) AS total_tokens, "
                "(SELECT COUNT(*) FROM kb_chunks WHERE kb_id = :kb_id) AS chunk_count, "
                "(SELECT COUNT(*) FROM kb_conversations WHERE kb_id = :kb_id) AS conversation_count, "
                "(SELECT COALESCE(index_status, 'none') FROM kb_knowledge_bases WHERE id = :kb_id) AS index_status"
            ), {"kb_id": kb_id}).mappings().first()
            if not row:
                return None
            return KbStatsEntity(
                kb_id=kb_id, doc_count=int(row["doc_count"] or 0),
                chunk_count=int(row["chunk_count"] or 0), total_tokens=int(row["total_tokens"] or 0),
                conversation_count=int(row["conversation_count"] or 0),
                index_status=row["index_status"] or "none",
            )

    # ---- Source ----

    def save_source(self, kb_id: str, source_type: str, source_url: str | None = None, source_path: str | None = None,
                    branch: str | None = None, file_count: int = 0, error: str | None = None):
        now = _now()
        with get_db() as db:
            db.execute(text(
                "INSERT INTO kb_sources (id, kb_id, source_type, source_url, source_path, branch, status, "
                "file_count, error, created_at, updated_at) "
                "VALUES (:id, :kb_id, :source_type, :source_url, :source_path, :branch, :status, "
                ":file_count, :error, :created_at, :updated_at)"
            ), {
                "id": str(uuid.uuid4()), "kb_id": kb_id, "source_type": source_type,
                "source_url": source_url, "source_path": source_path, "branch": branch,
                "status": "completed", "file_count": file_count, "error": error,
                "created_at": now, "updated_at": now,
            })

    def find_sources_by_kb_id(self, kb_id: str) -> list[dict]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, kb_id, source_type, source_url, source_path, branch, status, file_count, "
                "error, created_at, updated_at FROM kb_sources WHERE kb_id = :kb_id ORDER BY created_at DESC"
            ), {"kb_id": kb_id}).mappings().all()
            return [dict(r) for r in rows]

    def find_source_by_id(self, source_id: str) -> dict | None:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, kb_id, source_type, source_url, source_path, branch, status, file_count, "
                "error, created_at, updated_at FROM kb_sources WHERE id = :id"
            ), {"id": source_id}).mappings().first()
            return dict(row) if row else None

    def delete_source(self, source_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM kb_sources WHERE id = :id"), {"id": source_id})
            return result.rowcount > 0

    # ---- Index Meta ----

    def upsert_index_meta(self, kb_id: str, key: str, value: str):
        """Upsert a single meta field for a KB's index (aligned with Java upsertIndexMeta)."""
        # kb_index_meta uses kb_id as PK; columns are fixed fields
        with get_db() as db:
            # Check if row exists
            row = db.execute(text(
                "SELECT kb_id FROM kb_index_meta WHERE kb_id = :kb_id"
            ), {"kb_id": kb_id}).mappings().first()

            # Map known keys to columns
            column_map = {
                "index_type": "index_type",
                "embedding_dim": "embedding_dim",
                "chunk_count": "chunk_count",
                "index_path": "index_path",
                "built_at": "built_at",
                "status": "status",
            }
            col = column_map.get(key)
            if not col:
                return  # Unknown key, skip

            if row:
                db.execute(text(
                    f"UPDATE kb_index_meta SET {col} = :value WHERE kb_id = :kb_id"
                ), {"value": value, "kb_id": kb_id})
            else:
                db.execute(text(
                    f"INSERT INTO kb_index_meta (kb_id, {col}) VALUES (:kb_id, :value)"
                ), {"kb_id": kb_id, "value": value})

    def find_index_meta_by_kb_id(self, kb_id: str) -> dict[str, str]:
        with get_db() as db:
            row = db.execute(text(
                "SELECT kb_id, index_type, embedding_dim, chunk_count, index_path, built_at, status "
                "FROM kb_index_meta WHERE kb_id = :kb_id"
            ), {"kb_id": kb_id}).mappings().first()
            if not row:
                return {}
            return {k: str(v) if v is not None else "" for k, v in dict(row).items()}

    # ---- Conversions ----

    def _kb_params(self, e: KbKnowledgeBaseEntity) -> dict:
        return {
            "id": e.id, "name": e.name, "description": e.description,
            "tags": json.dumps(e.tags) if e.tags else None,
            "chunk_size": e.chunk_size, "chunk_overlap": e.chunk_overlap,
            "status": e.status, "embedding_model": e.embedding_model,
            "embedding_channel_id": e.embedding_channel_id, "embedding_dim": e.embedding_dim,
            "doc_count": e.doc_count, "chunk_count": e.chunk_count,
            "total_tokens": e.total_tokens, "index_status": e.index_status,
            "created_at": e.created_at, "updated_at": e.updated_at,
        }

    def _to_kb_entity(self, row) -> KbKnowledgeBaseEntity:
        return KbKnowledgeBaseEntity(
            id=row["id"], name=row["name"], description=row["description"],
            tags=json.loads(row["tags"]) if row["tags"] else None,
            chunk_size=row["chunk_size"], chunk_overlap=row["chunk_overlap"],
            status=row["status"], embedding_model=row["embedding_model"],
            embedding_channel_id=row["embedding_channel_id"], embedding_dim=row["embedding_dim"],
            doc_count=row["doc_count"] or 0, chunk_count=row["chunk_count"] or 0,
            total_tokens=row["total_tokens"] or 0, index_status=row["index_status"] or "none",
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def _doc_params(self, e: KbDocumentEntity) -> dict:
        return {
            "id": e.id, "kb_id": e.kb_id, "name": e.name, "source_type": e.source_type,
            "source_path": e.source_path, "status": e.status, "chunk_count": e.chunk_count,
            "total_tokens": e.total_tokens, "error_message": e.error_message,
            "created_at": e.created_at, "updated_at": e.updated_at,
        }

    def _to_doc_entity(self, row) -> KbDocumentEntity:
        return KbDocumentEntity(
            id=row["id"], kb_id=row["kb_id"], name=row["name"], source_type=row["source_type"],
            source_path=row["source_path"], status=row["status"], chunk_count=row["chunk_count"] or 0,
            total_tokens=row["total_tokens"] or 0, error_message=row["error_message"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def _chunk_params(self, e: KbChunkEntity) -> dict:
        return {
            "id": e.id, "doc_id": e.doc_id, "kb_id": e.kb_id, "content": e.content,
            "chunk_index": e.chunk_index, "token_count": e.token_count,
            "embedding": e.embedding, "chunk_type": e.chunk_type, "language": e.language,
            "metadata": e.metadata, "created_at": e.created_at,
        }

    def _to_chunk_entity(self, row) -> KbChunkEntity:
        return KbChunkEntity(
            id=row["id"], doc_id=row["doc_id"], kb_id=row["kb_id"], content=row["content"],
            chunk_index=row["chunk_index"], token_count=row["token_count"],
            embedding=row["embedding"] if isinstance(row["embedding"], bytes) else (row["embedding"].encode() if row["embedding"] else None),
            chunk_type=row["chunk_type"], language=row["language"], metadata=row["metadata"],
            created_at=row["created_at"],
        )

    def _task_params(self, e: KbTaskEntity) -> dict:
        return {
            "id": e.id, "kb_id": e.kb_id, "doc_id": e.doc_id, "task_type": e.task_type,
            "status": e.status, "progress": e.progress, "total_items": e.total_items,
            "done_items": e.done_items, "error_message": e.error_message,
            "created_at": e.created_at,
        }

    def _to_task_entity(self, row) -> KbTaskEntity:
        return KbTaskEntity(
            id=row["id"], kb_id=row["kb_id"], doc_id=row["doc_id"], task_type=row["task_type"],
            status=row["status"], progress=row["progress"], total_items=row["total_items"],
            done_items=row["done_items"], error_message=row["error_message"],
            created_at=row["created_at"], completed_at=row["completed_at"], payload=row.get("payload"),
            worker_id=row.get("worker_id"), lease_until=row.get("lease_until"),
            attempt_count=int(row.get("attempt_count") or 0), started_at=row.get("started_at"),
        )

    def save_task_payload(self, task_id: str, payload: dict) -> bool:
        with get_db() as db:
            result = db.execute(text("UPDATE kb_tasks SET payload=:payload WHERE id=:id"), {"payload": json.dumps(payload), "id": task_id})
            return result.rowcount == 1
