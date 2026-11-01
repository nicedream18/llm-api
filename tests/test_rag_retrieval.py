
import struct
from types import SimpleNamespace

from app.application.services.kb_service import KbService
from app.domain.entities import (
    KbChunkEntity,
    KbKnowledgeBaseEntity,
    ProxyResponseEntity,
    SearchResultEntity,
)
from app.domain.knowledge import RagContextBuilder, RagService, RetrieverService


class FakeRetriever:
    def __init__(self, results=None):
        self.results = results or []
        self.calls = []

    def keyword_search(self, kb_id, query, top_k):
        self.calls.append(("keyword", kb_id, query, top_k))
        return list(self.results)

    def vector_search(self, kb_id, embedding, top_k):
        self.calls.append(("vector", kb_id, embedding, top_k))
        return list(self.results)

    def hybrid_search(self, kb_id, query, embedding, top_k, vector_weight, keyword_weight):
        self.calls.append(("hybrid", vector_weight, keyword_weight))
        return list(self.results)


class FakeEmbedder:
    def __init__(self, error=None):
        self.error = error

    def embed(self, _query, _model):
        if self.error:
            raise self.error
        return [0.1, 0.2]


class NeverGateway:
    def __init__(self):
        self.called = False

    def forward_sync(self, _request):
        self.called = True
        return ProxyResponseEntity(success=True, body='{"choices":[{"message":{"content":"bad"}}]}')


def service(retriever, embedder):
    return RagService(retriever, embedder, NeverGateway(), RagContextBuilder())


def test_ask_falls_back_to_keyword_when_embedding_fails():
    result = SearchResultEntity(chunk_id="c1", doc_id="d1", content="answer")
    retriever = FakeRetriever([result])
    rag = service(retriever, FakeEmbedder(RuntimeError("embedding unavailable")))

    answer = rag.ask("kb", "question", "embed", "chat", 5)

    assert answer.sources[0]["filename"] == "d1"
    assert retriever.calls[0][0] == "keyword"


def test_ask_does_not_call_llm_when_retrieval_is_empty():
    retriever = FakeRetriever()
    rag = service(retriever, FakeEmbedder())

    answer = rag.ask("kb", "question", "embed", "chat", 5)

    assert answer.answer == "知识库中没有找到与问题相关的内容"
    assert answer.sources == []
    assert rag.gateway_service.called is False


def test_ask_with_config_passes_retrieval_weights():
    result = SearchResultEntity(chunk_id="c1", doc_id="d1", content="answer")
    retriever = FakeRetriever([result])
    rag = service(retriever, FakeEmbedder())

    rag.ask_with_config("kb", "question", "embed", "chat", 5, "hybrid", 0.2, 0.8)

    assert retriever.calls[-1] == ("hybrid", 0.2, 0.8)


def test_vector_search_uses_ready_hnsw_index_before_full_scan():
    class Repo:
        def find_kb_by_id(self, _kb_id):
            return SimpleNamespace(index_status="ready")

        def find_chunk_by_kb_id(self, _kb_id):
            raise AssertionError("ready index should avoid a full vector scan")

    class Index:
        def search_with_index(self, _kb_id, _embedding, _top_k):
            return [{"chunk_id": "c1", "doc_id": "d1", "content": "indexed", "score": 0.9}]

    retriever = RetrieverService(Repo(), object(), Index())

    results = retriever.vector_search("kb", [0.1, 0.2], 5)

    assert results[0].chunk_id == "c1"
    assert results[0].score == 0.9


def test_build_index_marks_kb_ready_and_records_embedding_dimension(monkeypatch, tmp_path):
    from app.domain import index_service

    class Repo:
        def __init__(self):
            self.kb = KbKnowledgeBaseEntity(id="kb-1", name="Test", index_status="stale")

        def find_chunk_by_kb_id(self, _kb_id):
            return [KbChunkEntity(id="c1", embedding=struct.pack("<2f", 1, 0))]

        def upsert_index_meta(self, *_args):
            return None

        def find_kb_by_id(self, _kb_id):
            return self.kb

        def update_kb(self, kb):
            self.kb = kb

    monkeypatch.setattr(index_service, "INDEX_DIR", str(tmp_path))
    repo = Repo()
    kb_service = KbService(repo, None, None, None)

    result = kb_service.build_index("kb-1")

    assert result["success"] is True
    assert result["embeddingDim"] == 2
    assert repo.kb.index_status == "ready"
    assert repo.kb.embedding_dim == 2
