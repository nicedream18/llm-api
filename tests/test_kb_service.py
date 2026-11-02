import base64

import pytest

from app.application.services.kb_service import KbService
from app.domain.entities import (
    KbChunkEntity,
    KbDocumentEntity,
    KbKnowledgeBaseEntity,
    KbTaskEntity,
    RagAnswerEntity,
    SearchResultEntity,
)
from app.domain.task_lease import TaskLease
from app.types.models import KbAskRequestDTO, KbSearchRequestDTO, UploadDocDTO


class FakeRepository:
    def __init__(self):
        self.kb = KbKnowledgeBaseEntity(
            id="kb-1", name="manual", chunk_size=128, chunk_overlap=10,
            embedding_model="embed-model", index_status="ready",
        )
        self.document = KbDocumentEntity(id="doc-1", kb_id="kb-1", name="guide.txt", status="pending")
        self.chunks = []
        self.tasks = {}
        self.conversations = []
        self.updated_kb = []
        self.updated_docs = []

    def find_kb_by_id(self, _kb_id):
        return self.kb

    def save_doc(self, document):
        self.document = document

    def update_task_status(self, task_id, status, error):
        self.tasks[task_id].status = status
        self.tasks[task_id].error_message = error

    def update_doc_status(self, doc_id, status, error):
        self.document.status = status
        self.document.error_message = error

    def find_doc_by_id(self, _doc_id):
        return self.document

    def update_doc(self, document):
        self.document = document
        self.updated_docs.append(document)

    def find_doc_by_kb_id(self, _kb_id):
        return [self.document]

    def publish_document(self, task_id, lease, kb_id, doc_id, chunks):
        lease.check()
        self.chunks = chunks
        self.document.status = "ready"
        self.document.chunk_count = len(chunks)
        self.document.total_tokens = sum(c.token_count for c in chunks)
        self.kb.index_status = "stale"
        self.kb.doc_count, self.kb.chunk_count, self.kb.total_tokens = 1, len(chunks), self.document.total_tokens
        self.update_task_status(task_id, "completed", None)

    def save_chunk_batch(self, chunks):
        self.chunks.extend(chunks)

    def find_chunk_by_kb_id(self, _kb_id):
        return self.chunks

    def update_task_progress(self, task_id, done, progress, lease):
        lease.check()
        task = self.tasks[task_id]
        task.done_items = done
        task.progress = progress

    def update_kb(self, kb):
        self.kb = kb
        self.updated_kb.append(kb)

    def save_conversation(self, kb_id, role, content):
        self.conversations.append((kb_id, role, content))

    def find_task_by_id(self, task_id):
        return self.tasks.get(task_id)

    def find_chunk_by_doc_id(self, _doc_id):
        return self.chunks

    def save_task(self, task, payload=None):
        self.tasks[task.id] = task
        if payload is not None:
            self.payload = payload


class FakeSplitter:
    def __init__(self):
        self.config = None
        self.content = None

    def split(self, content, file_type, config, metadata):
        self.content = content
        self.config = config
        return [KbChunkEntity(id="chunk-1", content=content, chunk_index=0, token_count=2, metadata='{"filePath":"guide.txt"}')]


class FakeEmbedder:
    def __init__(self, error=None):
        self.error = error

    def embed_batch(self, contents, model):
        if self.error:
            raise self.error
        self.call = (contents, model)
        return [[0.1, 0.2] for _ in contents]


class FakeRag:
    def __init__(self):
        self.calls = []
        self.answer = RagAnswerEntity(answer="grounded", sources=[{"filename": "guide.txt"}], usage={"total_tokens": 3})

    def ask_with_config(self, *args):
        self.calls.append(args)
        return self.answer

    def deep_research(self, *args):
        self.calls.append(args)
        return self.answer

    def search_by_mode(self, *args):
        self.calls.append(args)
        return [SearchResultEntity(chunk_id="c1", doc_id="d1", content="found", score=0.8,
                                  metadata={"filePath": "guide.txt"})]


def make_service(repo=None, rag=None, splitter=None, embedder=None):
    repo = repo or FakeRepository()
    rag = rag or FakeRag()
    splitter = splitter or FakeSplitter()
    embedder = embedder or FakeEmbedder()
    return KbService(repo, rag, splitter, embedder), repo, rag, splitter, embedder


def test_upload_doc_creates_pending_document_and_import_task():
    service, repo, *_ = make_service()

    result = service.upload_doc("kb-1", UploadDocDTO(filename="guide.txt", content="hello"))

    assert result.status == "pending"
    assert repo.document.kb_id == "kb-1"
    task = next(iter(repo.tasks.values()))
    assert task.status == "pending"
    assert task.doc_id == result.id
    assert repo.payload["content"] == "hello"


def test_import_pipeline_decodes_base64_embeds_and_invalidates_index():
    service, repo, _, splitter, embedder = make_service()
    dto = UploadDocDTO(filename="guide.txt", content=base64.b64encode(b"hello world").decode())
    task = KbTaskEntity(id="task-1", kb_id="kb-1", doc_id="doc-1")
    repo.tasks[task.id] = task

    service.run_import_pipeline("kb-1", "doc-1", "task-1", dto, lease=TaskLease("w", 1))

    assert splitter.content == "hello world"
    assert splitter.config.chunk_size == 128 and splitter.config.chunk_overlap == 10
    assert embedder.call == (["hello world"], "embed-model")
    assert repo.document.status == "ready" and repo.document.chunk_count == 1
    assert repo.chunks[0].embedding is not None
    assert repo.kb.index_status == "stale"
    assert (repo.kb.doc_count, repo.kb.chunk_count, repo.kb.total_tokens) == (1, 1, 2)
    assert task.status == "completed" and task.progress == 100


def test_import_pipeline_marks_task_running_before_missing_kb_fails():
    service, repo, *_ = make_service()
    task = KbTaskEntity(id="task-1", kb_id="kb-1", doc_id="doc-1")
    repo.tasks[task.id] = task
    repo.find_kb_by_id = lambda _kb_id: None

    with pytest.raises(ValueError, match="KB not found"):
        service.run_import_pipeline("kb-1", "doc-1", "task-1", UploadDocDTO(filename="a.txt", content="x"), lease=TaskLease("w", 1))

    assert task.status == "pending"
    assert repo.document.status == "pending"
    assert repo.chunks == []


def test_ask_uses_supplied_search_config_and_persists_both_turns():
    service, repo, rag, *_ = make_service()
    request = KbAskRequestDTO(question="where?", model="chat-model", top_k=7,
                              search_mode="hybrid", vector_weight=0.2, keyword_weight=0.8)

    response = service.ask("kb-1", request)

    assert rag.calls[0][:8] == ("kb-1", "where?", "embed-model", "chat-model", 7, "hybrid", 0.2, 0.8)
    assert response.answer == "grounded"
    assert [source["filename"] for source in response.sources] == ["guide.txt"]
    assert repo.conversations == [("kb-1", "user", "where?"), ("kb-1", "assistant", "grounded")]


def test_search_maps_retrieval_metadata_and_task_reads_are_kb_scoped():
    service, repo, rag, *_ = make_service()
    results = service.search_kb("kb-1", KbSearchRequestDTO(query="found", search_mode="keyword"))
    task = KbTaskEntity(id="task-1", kb_id="kb-1", doc_id="doc-1", status="completed", progress=100)
    repo.tasks[task.id] = task

    assert results[0].filename == "guide.txt" and results[0].score == 0.8
    assert rag.calls[0] == ("kb-1", "found", 5, "keyword", "embed-model")
    assert service.get_task("other-kb", "task-1") == {}
    assert service.get_task("kb-1", "task-1")["status"] == "completed"
