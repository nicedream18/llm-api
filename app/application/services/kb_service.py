"""KB, Security, Agent, and Proxy application services."""
import base64
import binascii
import logging
import uuid
from datetime import UTC, datetime
from io import BytesIO

from app.application.errors import ApplicationError
from app.domain.entities import (
    KbDocumentEntity,
    KbKnowledgeBaseEntity,
    KbTaskEntity,
)
from app.domain.importer import SUPPORTED_EXTS
from app.types.models import (
    CreateKbDTO,
    KbAskRequestDTO,
    KbAskResponseDTO,
    KbDocumentDTO,
    KbKnowledgeBaseDTO,
    KbSearchRequestDTO,
    KbSearchResultDTO,
    KbStatsDTO,
    KbTagDTO,
    UploadDocDTO,
)

logger = logging.getLogger(__name__)
MAX_DOCUMENT_CONTENT_CHARS = 70_000_000


def _now():
    return datetime.now(UTC).isoformat()


def extract_pdf_text(content: bytes) -> str:
    """Extract text from a PDF without invoking shell tools or OCR services."""
    if not content.startswith(b"%PDF"):
        raise ValueError("Invalid PDF content")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF parsing support is not installed") from exc
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise ValueError("PDF parsing failed") from exc
    text = "\n\n".join(page for page in pages if page)
    if not text.strip():
        raise ValueError("PDF contains no extractable text")
    return text


class KbService:
    def __init__(self, kb_repository, rag_service, text_splitter, embedder_service, proxy_service=None):
        self.repo = kb_repository
        self.rag = rag_service
        self.splitter = text_splitter
        self.embedder = embedder_service
        self.proxy = proxy_service

    def _model_operation(self, operation, *args, auth_context=None):
        from app.domain.model_policy import model_operation
        with model_operation(self.proxy, auth_context):
            return operation(*args)

    def create_kb(self, dto: CreateKbDTO):
        now = _now()
        entity = KbKnowledgeBaseEntity(
            id=str(uuid.uuid4()), name=dto.name, description=dto.description, tags=dto.tags,
            chunk_size=dto.chunk_size or 512, chunk_overlap=dto.chunk_overlap or 50,
            status=1, embedding_model=dto.embedding_model,
            embedding_channel_id=dto.embedding_channel_id, embedding_dim=0,
            index_status="none", created_at=now, updated_at=now,
        )
        self.repo.save_kb(entity)
        return self._to_kb_dto(entity)

    def get_kb(self, kb_id):
        return self._to_kb_dto(self.repo.find_kb_by_id(kb_id))

    def list_kbs(self):
        return [self._to_kb_dto(e) for e in self.repo.find_all_kb()]

    def update_kb(self, kb_id, dto: KbKnowledgeBaseDTO):
        entity = self.repo.find_kb_by_id(kb_id)
        if not entity: return False
        if dto.name is not None: entity.name = dto.name
        if dto.description is not None: entity.description = dto.description
        if dto.tags is not None: entity.tags = dto.tags
        if dto.chunk_size is not None: entity.chunk_size = dto.chunk_size
        if dto.chunk_overlap is not None: entity.chunk_overlap = dto.chunk_overlap
        if dto.status is not None: entity.status = dto.status
        if dto.embedding_model is not None: entity.embedding_model = dto.embedding_model
        if dto.embedding_channel_id is not None: entity.embedding_channel_id = dto.embedding_channel_id
        self.repo.update_kb(entity)
        return True

    def delete_kb(self, kb_id):
        from app.domain.index_service import IndexService
        index_service = IndexService(self.repo)
        index_service.validate_kb_id(kb_id)
        deleted = self.repo.delete_kb_by_id(kb_id)
        if deleted is False:
            return False
        try:
            index_service.remove_index_file(kb_id)
        except OSError:
            logger.warning("Failed to remove deleted knowledge base index file", exc_info=True)
        return True

    def upload_doc(self, kb_id, dto: UploadDocDTO):
        if not self.repo.find_kb_by_id(kb_id):
            raise ApplicationError("Knowledge base not found", 404, "not_found")
        filename = dto.filename or ""
        if not filename or len(filename) > 256 or any(char in filename for char in ("/", "\\", "\x00")) or filename in {".", ".."}:
            raise ApplicationError("Invalid document filename", 422, "invalid_filename")
        file_type = (dto.file_type or filename.rsplit(".", 1)[-1] or "txt").lower()
        if file_type not in SUPPORTED_EXTS:
            raise ApplicationError("Unsupported document type", 422, "unsupported_file_type")
        if len(dto.content) > MAX_DOCUMENT_CONTENT_CHARS:
            raise ApplicationError("Document exceeds the size limit", 413, "size_limit")
        now = _now()
        entity = KbDocumentEntity(
            id=str(uuid.uuid4()), kb_id=kb_id, name=dto.filename,
            source_type=dto.source_type or "file", source_path=filename,
            status="pending", chunk_count=0, total_tokens=0, created_at=now, updated_at=now,
        )
        self.repo.save_doc(entity)
        task = KbTaskEntity(
            id=str(uuid.uuid4()), kb_id=kb_id, doc_id=entity.id, task_type="import",
            status="pending", progress=0, total_items=0, done_items=0, created_at=now,
        )
        self.repo.save_task(task, {"filename": filename, "content": dto.content, "file_type": file_type, "source_type": dto.source_type})
        return self._to_doc_dto(entity)

    def run_import_pipeline(self, kb_id, doc_id, task_id, dto, *, lease):
        lease.check()
        try:
            kb = self.repo.find_kb_by_id(kb_id)
            if not kb:
                raise ValueError("KB not found: " + kb_id)
            raw_content = dto.content
            decoded_bytes = None
            try:
                decoded_bytes = base64.b64decode(raw_content, validate=True)
            except (binascii.Error, ValueError, TypeError):
                pass
            if (dto.file_type or "").lower() == "pdf":
                if decoded_bytes is None:
                    raise ValueError("PDF content must be Base64 encoded")
                content = extract_pdf_text(decoded_bytes)
            elif decoded_bytes is not None:
                try:
                    content = decoded_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    content = raw_content
            else:
                content = raw_content
            from app.domain.knowledge import ChunkConfig
            chunk_config = ChunkConfig(chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap)
            metadata = {"filePath": dto.filename}
            chunks = self.splitter.split(content, dto.file_type or "txt", chunk_config, metadata)
            if not chunks:
                raise ValueError("Empty content or no chunks")
            embedding_model = kb.embedding_model or "text-embedding-3-small"
            chunk_contents = [c.content for c in chunks]
            from app.domain.knowledge import serialize_embedding
            embeddings = self.embedder.embed_batch(chunk_contents, embedding_model)
            now = _now()
            total_tokens = 0
            for i, chunk in enumerate(chunks):
                chunk.kb_id = kb_id
                chunk.doc_id = doc_id
                chunk.created_at = now
                if i < len(embeddings) and embeddings[i]:
                    chunk.embedding = serialize_embedding(embeddings[i])
                total_tokens += chunk.token_count or 0
                self.repo.update_task_progress(task_id, i + 1, int((i + 1) * 100.0 / len(chunks)), lease)
            self.repo.publish_document(task_id, lease, kb_id, doc_id, chunks)
            logger.info(f"Import pipeline done: kbId={kb_id}, docId={doc_id}, chunks={len(chunks)}")
        except Exception:
            logger.error("Import pipeline failed", extra={"kb_id": kb_id, "doc_id": doc_id, "task_id": task_id})
            raise

    def list_docs(self, kb_id):
        return [self._to_doc_dto(e) for e in self.repo.find_doc_by_kb_id(kb_id)]

    def delete_doc(self, kb_id, doc_id):
        document = self.repo.find_doc_by_id(doc_id)
        if not document or document.kb_id != kb_id:
            return False
        result = self.repo.delete_doc_by_id(doc_id)
        return result is not False

    def ask(self, kb_id, request: KbAskRequestDTO, auth_context=None):
        kb = self.repo.find_kb_by_id(kb_id)
        if not kb:
            return KbAskResponseDTO(answer="\u77e5\u8bc6\u5e93\u4e0d\u5b58\u5728")
        embedding_model = kb.embedding_model or "text-embedding-3-small"
        chat_model = request.model or "gpt-4.1"
        top_k = request.top_k or 5
        history = request.history
        answer = self._model_operation(self.rag.ask_with_config,
            kb_id, request.question, embedding_model, chat_model, top_k,
            request.search_mode or "hybrid",
            request.vector_weight if request.vector_weight is not None else 0.7,
            request.keyword_weight if request.keyword_weight is not None else 0.3,
            history, auth_context=auth_context,
        )
        self.repo.save_conversation(kb_id, "user", request.question)
        self.repo.save_conversation(kb_id, "assistant", answer.answer)
        return self._to_ask_response(answer)

    def deep_research(self, kb_id, request: KbAskRequestDTO, auth_context=None):
        kb = self.repo.find_kb_by_id(kb_id)
        if not kb:
            return KbAskResponseDTO(answer="\u77e5\u8bc6\u5e93\u4e0d\u5b58\u5728")
        embedding_model = kb.embedding_model or "text-embedding-3-small"
        chat_model = request.model or "gpt-4.1"
        top_k = request.top_k or 5
        max_rounds = request.max_rounds or 3
        answer = self._model_operation(self.rag.deep_research, kb_id, request.question, embedding_model, chat_model, top_k, max_rounds, auth_context=auth_context)
        self.repo.save_conversation(kb_id, "user", request.question)
        self.repo.save_conversation(kb_id, "assistant", answer.answer)
        return self._to_ask_response(answer)

    def get_conversations(self, kb_id):
        return self.repo.find_conversation_by_kb_id(kb_id)

    def get_task(self, kb_id, task_id):
        entity = self.repo.find_task_by_id(task_id)
        if not entity or entity.kb_id != kb_id:
            return {}
        return {
            "id": entity.id, "kbId": entity.kb_id, "docId": entity.doc_id,
            "taskType": entity.task_type, "status": entity.status, "progress": entity.progress,
            "totalItems": entity.total_items, "doneItems": entity.done_items,
            "errorMessage": entity.error_message, "createdAt": entity.created_at,
            "completedAt": entity.completed_at,
        }

    def search_kb(self, kb_id, request: KbSearchRequestDTO, auth_context=None):
        top_k = request.top_k or 5
        search_mode = request.search_mode or "keyword"
        kb = self.repo.find_kb_by_id(kb_id)
        embedding_model = kb.embedding_model if kb else "text-embedding-3-small"
        results = self._model_operation(self.rag.search_by_mode, kb_id, request.query, top_k, search_mode, embedding_model, auth_context=auth_context)
        return [KbSearchResultDTO(chunk_id=r.chunk_id, doc_id=r.doc_id, filename=r.metadata.get("filePath") if r.metadata else None,
                                   content=r.content, score=r.score, metadata=r.metadata) for r in results]

    def get_kb_stats(self, kb_id):
        entity = self.repo.get_kb_stats(kb_id)
        if not entity: return None
        return KbStatsDTO(kb_id=entity.kb_id, doc_count=entity.doc_count, chunk_count=entity.chunk_count,
                          total_tokens=entity.total_tokens, conversation_count=entity.conversation_count,
                          index_status=entity.index_status)

    def clear_conversations(self, kb_id):
        return self.repo.clear_conversations(kb_id)

    def refresh_tags(self, kb_id, limit=10):
        """Refresh tags by re-scanning all documents in the knowledge base."""
        return self.get_tags(kb_id, limit)

    def search(self, kb_id, request: KbSearchRequestDTO, auth_context=None):
        """Search KB with mode (vector/keyword/hybrid). Route entry for POST /{id}/search."""
        return self.search_kb(kb_id, request, auth_context=auth_context)

    def stats(self, kb_id):
        """Get KB statistics. Route entry for GET /{id}/stats."""
        return self.get_kb_stats(kb_id)

    def reindex_doc(self, kb_id, doc_id):
        """Reindex a single document. Route entry for POST /{id}/documents/{docId}/reindex."""
        doc = self.repo.find_doc_by_id(doc_id)
        if not doc or doc.kb_id != kb_id:
            return {"success": False, "message": "Document not found"}
        chunks = self.repo.find_chunk_by_doc_id(doc_id)
        if not chunks:
            return {"success": False, "message": "No chunks found for document"}
        now = _now()
        task = KbTaskEntity(
            id=str(uuid.uuid4()), kb_id=kb_id, doc_id=doc_id, task_type="reindex",
            status="pending", progress=0, total_items=0, done_items=0, created_at=now,
        )
        self.repo.save_task(task)
        return {"success": True, "taskId": task.id, "message": "Reindex started"}

    def run_reindex_pipeline(self, kb_id, doc_id, task_id, chunks, *, lease):
        lease.check()
        try:
            kb = self.repo.find_kb_by_id(kb_id)
            embedding_model = kb.embedding_model if kb else "text-embedding-3-small"
            from app.domain.knowledge import serialize_embedding
            chunk_contents = [c.content for c in chunks]
            embeddings = self.embedder.embed_batch(chunk_contents, embedding_model)
            for i, chunk in enumerate(chunks):
                if i < len(embeddings) and embeddings[i]:
                    chunk.embedding = serialize_embedding(embeddings[i])
                self.repo.update_task_progress(task_id, i + 1, int((i + 1) * 100.0 / len(chunks)), lease)
            self.repo.publish_document(task_id, lease, kb_id, doc_id, chunks)
            logger.info(f"Reindex done: kbId={kb_id}, docId={doc_id}, chunks={len(chunks)}")
        except Exception as e:
            logger.error(f"Reindex failed: kbId={kb_id}, docId={doc_id}: {e}")
            raise

    def cancel_task(self, kb_id, task_id):
        return self.repo.cancel_task(kb_id, task_id)

    def get_doc(self, kb_id, doc_id):
        """Get document detail. Route entry for GET /{id}/documents/{docId}."""
        entity = self.repo.find_doc_by_id(doc_id)
        if not entity or entity.kb_id != kb_id:
            return None
        return self._to_doc_dto(entity)

    def get_index_info(self, kb_id):
        """Get index info. Route entry for GET /{id}/index."""
        kb = self.repo.find_kb_by_id(kb_id)
        if not kb:
            return None
        return {
            "kbId": kb_id,
            "indexStatus": kb.index_status or "none",
            "chunkCount": kb.chunk_count,
            "docCount": kb.doc_count,
            "totalTokens": kb.total_tokens,
        }

    def build_index(self, kb_id):
        """Build HNSW index for KB. Route entry for POST /{id}/index."""
        from app.domain.index_service import IndexService
        kb = self.repo.find_kb_by_id(kb_id)
        if not kb:
            return {"success": False, "message": "Knowledge base not found"}
        expected_updated_at = kb.updated_at
        index_service = IndexService(self.repo)
        result = index_service.build_index(kb_id)
        status = "ready" if result.get("success") else "error"
        embedding_dim = int(result["embeddingDim"]) if result.get("success") and result.get("embeddingDim") else None
        if hasattr(self.repo, "set_index_state_if_unchanged"):
            updated = self.repo.set_index_state_if_unchanged(kb_id, expected_updated_at, status, embedding_dim)
            if not updated and result.get("success"):
                index_service.remove_index_file(kb_id)
                result["indexStatus"] = "stale"
        else:
            kb.index_status = status
            if embedding_dim is not None:
                kb.embedding_dim = embedding_dim
            self.repo.update_kb(kb)
        return result

    def drop_index(self, kb_id):
        """Drop HNSW index for KB. Route entry for DELETE /{id}/index."""
        from app.domain.index_service import IndexService
        index_service = IndexService(self.repo)
        result = index_service.drop_index(kb_id)
        kb = self.repo.find_kb_by_id(kb_id)
        if kb:
            kb.index_status = "none"
            self.repo.update_kb(kb)
        return result

    def list_sources(self, kb_id):
        """List import sources. Route entry for GET /{id}/sources."""
        return self.repo.find_sources_by_kb_id(kb_id)

    def create_source(self, kb_id, body):
        """Create import source. Route entry for POST /{id}/sources."""
        if not self.repo.find_kb_by_id(kb_id):
            raise ApplicationError("Knowledge base not found", 404, "not_found")
        from app.domain.importer import ImporterService
        importer = ImporterService(self.repo, self.splitter, self.embedder)
        return importer.import_source(kb_id, body)

    def delete_source(self, kb_id, source_id):
        """Delete import source. Route entry for DELETE /{id}/sources/{sourceId}."""
        source = self.repo.find_source_by_id(source_id)
        if not source or source.get("kb_id") != kb_id:
            return False
        self.repo.delete_source(source_id)
        return True

    def get_tags(self, kb_id, limit=10):
        contents = self.repo.sample_contents(kb_id, 200)
        word_freq = {}
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "can", "this", "that", "these", "those", "it", "its", "for", "and", "or", "but", "in", "on", "at", "to", "of", "from", "by", "with", "as"}
        for content in contents:
            self._extract_words(content, word_freq, stopwords)
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [KbTagDTO(word=w, count=c) for w, c in sorted_words]

    def _extract_words(self, text, word_freq, stopwords):
        import re
        for m in re.finditer(r"[a-zA-Z]{4,}", text):
            word = m.group().lower()
            if word not in stopwords:
                word_freq[word] = word_freq.get(word, 0) + 1
        prev_cjk = None
        for ch in text:
            is_cjk = 0x4E00 <= ord(ch) <= 0x9FFF or 0x3400 <= ord(ch) <= 0x4DBF
            if is_cjk:
                if prev_cjk:
                    bigram = prev_cjk + ch
                    if prev_cjk not in stopwords and ch not in stopwords:
                        word_freq[bigram] = word_freq.get(bigram, 0) + 1
                prev_cjk = ch
            else:
                prev_cjk = None

    def _to_kb_dto(self, e):
        if not e: return None
        return KbKnowledgeBaseDTO(id=e.id, name=e.name, description=e.description, tags=e.tags,
                                  chunk_size=e.chunk_size, chunk_overlap=e.chunk_overlap,
                                  doc_count=e.doc_count, chunk_count=e.chunk_count, total_tokens=e.total_tokens,
                                  status=e.status, index_status=e.index_status, embedding_model=e.embedding_model,
                                  embedding_channel_id=e.embedding_channel_id, embedding_dim=e.embedding_dim,
                                  created_at=e.created_at, updated_at=e.updated_at)

    def _to_doc_dto(self, e):
        if not e: return None
        return KbDocumentDTO(id=e.id, kb_id=e.kb_id, name=e.name, source_type=e.source_type,
                             source_path=e.source_path, status=e.status, chunk_count=e.chunk_count,
                             total_tokens=e.total_tokens, error_message=e.error_message,
                             created_at=e.created_at, updated_at=e.updated_at)

    def _to_ask_response(self, entity):
        sources = []
        if entity.sources:
            for s in entity.sources:
                sources.append({"filename": s.get("filename"), "score": s.get("score"), "snippet": s.get("snippet")})
        return KbAskResponseDTO(answer=entity.answer, sources=sources, usage=entity.usage,
                                retrieval_details=entity.retrieval_details or [])
