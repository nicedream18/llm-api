import struct

import pytest

from app.application.errors import ApplicationError
from app.application.services.kb_service import KbService
from app.domain.entities import (
    KbChunkEntity,
    KbDocumentEntity,
    KbKnowledgeBaseEntity,
    KbStatsEntity,
    RagAnswerEntity,
    SearchResultEntity,
)
from app.domain.task_lease import TaskLease
from app.types.models import (
    CreateKbDTO,
    KbAskRequestDTO,
    KbKnowledgeBaseDTO,
    KbSearchRequestDTO,
    UploadDocDTO,
)


class FakeRepository:
    def __init__(self):
        self.kb = KbKnowledgeBaseEntity(
            id="kb-1", name="Manual", chunk_size=100, chunk_overlap=10,
            embedding_model="embed-model", index_status="ready",
        )
        self.documents = {
            "doc-1": KbDocumentEntity(
                id="doc-1", kb_id="kb-1", name="guide.md", status="ready",
                chunk_count=1, total_tokens=4,
            )
        }
        self.chunks = [
            KbChunkEntity(
                id="chunk-1", kb_id="kb-1", doc_id="doc-1", content="alpha beta",
                chunk_index=0, token_count=4, embedding=struct.pack("<2f", 1, 0),
                metadata='{"filePath":"guide.md"}',
            )
        ]
        self.tasks = {}
        self.sources = {"source-1": {"id": "source-1", "kb_id": "kb-1"}}
        self.conversations = []
        self.kbs_saved = []
        self.kbs_updated = []
        self.doc_status = []
        self.task_status = []
        self.progress = []
        self.deleted_docs = []
        self.atomic_index_result = True
        self.atomic_index_calls = []

    def save_kb(self, kb):
        self.kb = kb
        self.kbs_saved.append(kb)

    def find_kb_by_id(self, kb_id):
        return self.kb if self.kb and self.kb.id == kb_id else None

    def find_all_kb(self):
        return [self.kb] if self.kb else []

    def update_kb(self, kb):
        self.kb = kb
        self.kbs_updated.append(kb)

    def delete_kb_by_id(self, kb_id):
        if not self.kb or self.kb.id != kb_id:
            return False
        self.kb = None
        return True

    def save_doc(self, document):
        self.documents[document.id] = document

    def update_doc(self, document):
        self.documents[document.id] = document

    def update_doc_status(self, doc_id, status, error):
        self.doc_status.append((doc_id, status, error))
        if doc_id in self.documents:
            self.documents[doc_id].status = status
            self.documents[doc_id].error_message = error

    def find_doc_by_id(self, doc_id):
        return self.documents.get(doc_id)

    def find_doc_by_kb_id(self, kb_id):
        return [doc for doc in self.documents.values() if doc.kb_id == kb_id]

    def delete_doc_by_id(self, doc_id):
        self.deleted_docs.append(doc_id)
        return self.documents.pop(doc_id, None) is not None

    def save_task(self, task, payload=None):
        self.tasks[task.id] = task
        task.payload_value = payload

    def update_task_status(self, task_id, status, error):
        self.task_status.append((task_id, status, error))
        self.tasks[task_id].status = status
        self.tasks[task_id].error_message = error

    def update_task_progress(self, task_id, done, progress, lease):
        lease.check()
        self.progress.append((task_id, done, progress))
        self.tasks[task_id].done_items = done
        self.tasks[task_id].progress = progress

    def find_task_by_id(self, task_id):
        return self.tasks.get(task_id)

    def find_chunk_by_kb_id(self, _kb_id):
        return self.chunks

    def find_chunk_by_doc_id(self, doc_id):
        return [chunk for chunk in self.chunks if chunk.doc_id == doc_id]

    def publish_document(self, task_id, lease, kb_id, doc_id, chunks):
        lease.check()
        self.chunks = chunks
        self.update_doc_status(doc_id, "ready", None)
        self.kb.index_status = "stale"
        self.update_task_status(task_id, "completed", None)

    def save_chunk_batch(self, chunks):
        self.chunks.extend(chunks)

    def update_chunk_embedding(self, chunk_id, embedding):
        next(chunk for chunk in self.chunks if chunk.id == chunk_id).embedding = embedding

    def save_conversation(self, kb_id, role, content):
        self.conversations.append((kb_id, role, content))

    def find_conversation_by_kb_id(self, kb_id):
        return [row for row in self.conversations if row[0] == kb_id]

    def clear_conversations(self, kb_id):
        before = len(self.conversations)
        self.conversations = [row for row in self.conversations if row[0] != kb_id]
        return before - len(self.conversations)

    def get_kb_stats(self, kb_id):
        if kb_id != "kb-1":
            return None
        return KbStatsEntity(
            kb_id=kb_id, doc_count=1, chunk_count=1, total_tokens=4,
            conversation_count=len(self.conversations), index_status=self.kb.index_status,
        )

    def sample_contents(self, _kb_id, _limit):
        return ["alpha beta alpha", "the useful guide", "你好世界你好"]

    def find_source_by_id(self, source_id):
        return self.sources.get(source_id)

    def find_sources_by_kb_id(self, kb_id):
        return [source for source in self.sources.values() if source.get("kb_id") == kb_id]

    def delete_source(self, source_id):
        self.sources.pop(source_id, None)

    def set_index_state_if_unchanged(self, kb_id, updated_at, status, embedding_dim):
        self.atomic_index_calls.append((kb_id, updated_at, status, embedding_dim))
        if self.atomic_index_result and self.kb:
            self.kb.index_status = status
            if embedding_dim is not None:
                self.kb.embedding_dim = embedding_dim
        return self.atomic_index_result


class FakeSplitter:
    def split(self, content, file_type, config, metadata):
        return [
            KbChunkEntity(
                id="new-chunk", content=content, token_count=3,
                metadata='{"filePath":"guide.txt"}',
            )
        ]


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def embed_batch(self, contents, model):
        self.calls.append((contents, model))
        return [[0.0, 1.0] for _ in contents]


class FakeRag:
    def __init__(self):
        self.calls = []

    def ask_with_config(self, *args):
        self.calls.append(("ask", args))
        return RagAnswerEntity(answer="grounded", sources=[], usage={"total_tokens": 2})

    def deep_research(self, *args):
        self.calls.append(("research", args))
        return RagAnswerEntity(answer="researched", sources=[])

    def search_by_mode(self, *args):
        self.calls.append(("search", args))
        return [SearchResultEntity(
            chunk_id="chunk-1", doc_id="doc-1", content="alpha", score=0.7,
            metadata={"filePath": "guide.md"},
        )]


def make_service(repository=None, rag=None):
    repository = repository or FakeRepository()
    rag = rag or FakeRag()
    embedder = FakeEmbedder()
    return KbService(repository, rag, FakeSplitter(), embedder), repository, rag, embedder


def test_kb_crud_maps_entities_and_deletes_index_file(monkeypatch, tmp_path):
    from app.domain.index_service import IndexService

    monkeypatch.setattr("app.domain.index_service.INDEX_DIR", str(tmp_path))
    repository = FakeRepository()
    service, _, _, _ = make_service(repository)

    created = service.create_kb(CreateKbDTO(name="New KB", chunk_size=256, chunk_overlap=16))
    assert created.name == "New KB" and created.chunk_size == 256
    assert created.index_status == "none"
    assert service.get_kb(created.id).id == created.id
    assert [item.id for item in service.list_kbs()] == [created.id]

    updated = service.update_kb(
        created.id,
        KbKnowledgeBaseDTO(name="Renamed", description="Description", tags=["docs"]),
    )
    assert updated is True
    assert repository.kb.name == "Renamed" and repository.kb.tags == ["docs"]
    assert service.update_kb("missing", KbKnowledgeBaseDTO(name="unused")) is False

    index_path = tmp_path / f"{created.id}.index"
    index_path.write_text("index", encoding="utf-8")
    assert service.delete_kb(created.id) is True
    assert not index_path.exists()
    assert service.delete_kb(created.id) is False
    with pytest.raises(ValueError, match="Invalid knowledge base id"):
        IndexService(repository).validate_kb_id("../outside")


@pytest.mark.parametrize(
    ("filename", "file_type", "expected_code"),
    [
        ("../secret.txt", "txt", "invalid_filename"),
        ("guide.unsupported", "unsupported", "unsupported_file_type"),
    ],
)
def test_upload_doc_rejects_invalid_file_metadata(filename, file_type, expected_code):
    service, _, _, _ = make_service()

    with pytest.raises(ApplicationError) as error:
        service.upload_doc(
            "kb-1", UploadDocDTO(filename=filename, content="x", file_type=file_type)
        )

    assert error.value.code == expected_code


def test_upload_doc_and_delete_doc_are_scoped_to_existing_kb():
    service, repository, _, _ = make_service()
    uploaded = service.upload_doc(
        "kb-1", UploadDocDTO(filename="new.txt", content="raw text")
    )

    assert uploaded.status == "pending"
    assert next(task for task in repository.tasks.values() if task.doc_id == uploaded.id).payload_value == {
        "filename": "new.txt", "content": "raw text", "file_type": "txt", "source_type": "file",
    }
    with pytest.raises(ApplicationError) as error:
        service.upload_doc("missing", UploadDocDTO(filename="new.txt", content="x"))
    assert error.value.code == "not_found"
    assert service.delete_doc("other-kb", "doc-1") is False
    assert service.delete_doc("kb-1", "doc-1") is True
    assert repository.deleted_docs == ["doc-1"]


def test_ask_deep_research_search_and_conversation_management():
    service, repository, rag, _ = make_service()
    ask = service.ask(
        "kb-1", KbAskRequestDTO(question="where?", top_k=6, model="chat-model")
    )
    research = service.deep_research(
        "kb-1", KbAskRequestDTO(question="why?", max_rounds=4)
    )
    results = service.search("kb-1", KbSearchRequestDTO(query="alpha", top_k=3))

    assert ask.answer == "grounded" and research.answer == "researched"
    assert rag.calls[0] == (
        "ask", ("kb-1", "where?", "embed-model", "chat-model", 6,
                "hybrid", 0.7, 0.3, None),
    )
    assert rag.calls[1] == (
        "research", ("kb-1", "why?", "embed-model", "gpt-4.1", 5, 4),
    )
    assert results[0].filename == "guide.md"
    assert service.get_conversations("kb-1") == repository.conversations
    assert service.stats("kb-1").doc_count == 1
    assert service.stats("missing") is None
    assert service.clear_conversations("kb-1") == 4
    assert service.get_conversations("kb-1") == []
    assert service.ask("missing", KbAskRequestDTO(question="q")).answer == "知识库不存在"


def test_tags_extract_english_terms_and_cjk_bigrams():
    service, _, _, _ = make_service()

    tags = service.get_tags("kb-1", 10)

    english = {tag.word: tag.count for tag in tags if tag.word.isascii()}
    cjk = [tag for tag in tags if not tag.word.isascii()]
    assert english == {"alpha": 2, "beta": 1, "useful": 1, "guide": 1}
    assert {tag.word for tag in cjk} == {"你好", "好世", "世界", "界你"}
    assert next(tag.count for tag in cjk if tag.word == "你好") == 2


def test_reindex_doc_and_pipeline_update_progress_and_mark_index_stale():
    service, repository, _, embedder = make_service()

    queued = service.reindex_doc("kb-1", "doc-1")
    task_id = queued["taskId"]
    task = repository.tasks[task_id]
    assert queued["success"] is True and task.task_type == "reindex"
    assert service.reindex_doc("other-kb", "doc-1")["success"] is False
    assert service.reindex_doc("kb-1", "missing")["success"] is False

    service.run_reindex_pipeline("kb-1", "doc-1", task_id, repository.chunks, lease=TaskLease("w", 1))

    assert embedder.calls[-1] == (["alpha beta"], "embed-model")
    assert repository.chunks[0].embedding == struct.pack("<2f", 0.0, 1.0)
    assert repository.doc_status[-1] == ("doc-1", "ready", None)
    assert repository.progress[-1] == (task_id, 1, 100)
    assert repository.task_status[-1] == (task_id, "completed", None)
    assert repository.kb.index_status == "stale"


def test_index_state_race_removes_unpublished_file(monkeypatch):
    from app.domain.index_service import IndexService

    repository = FakeRepository()
    repository.atomic_index_result = False
    service, _, _, _ = make_service(repository)
    removed = []
    monkeypatch.setattr(
        IndexService, "build_index", lambda _self, _kb_id: {
            "success": True, "embeddingDim": 2,
        },
    )
    monkeypatch.setattr(IndexService, "remove_index_file", lambda _self, kb_id: removed.append(kb_id) or True)

    result = service.build_index("kb-1")

    assert result["indexStatus"] == "stale"
    assert removed == ["kb-1"]
    assert repository.atomic_index_calls == [("kb-1", repository.kb.updated_at, "ready", 2)]


def test_index_status_sources_and_document_lookup_are_scoped(monkeypatch):
    from app.domain.index_service import IndexService

    service, repository, _, _ = make_service()
    monkeypatch.setattr(IndexService, "drop_index", lambda _self, _kb_id: {"success": True})

    assert service.get_doc("other-kb", "doc-1") is None
    assert service.get_doc("kb-1", "doc-1").name == "guide.md"
    assert service.get_index_info("kb-1")["indexStatus"] == "ready"
    assert service.get_index_info("missing") is None
    assert service.list_sources("kb-1")[0]["id"] == "source-1"
    assert service.delete_source("other-kb", "source-1") is False
    assert service.delete_source("kb-1", "source-1") is True
    assert service.drop_index("kb-1")["success"] is True
    assert repository.kb.index_status == "none"
