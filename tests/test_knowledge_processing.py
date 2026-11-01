import json
import struct
from types import SimpleNamespace

import pytest

from app.domain.entities import KbChunkEntity, ProxyResponseEntity, SearchResultEntity
from app.domain.knowledge import (
    ChunkConfig,
    EmbedderService,
    RagContextBuilder,
    RagService,
    RetrieverService,
    TextSplitter,
    cosine_similarity,
    deserialize_embedding,
    serialize_embedding,
)


def test_text_splitter_tracks_markdown_heading_per_section_and_subchunk():
    splitter = TextSplitter()

    sections = splitter.split(
        "# Alpha\nfirst section\n# Beta\nsecond section",
        "md", ChunkConfig(100, 0), {"filePath": "guide.md"},
    )
    assert [json.loads(chunk.metadata)["heading"] for chunk in sections] == ["# Alpha", "# Beta"]
    assert all(json.loads(chunk.metadata)["filePath"] == "guide.md" for chunk in sections)

    subchunks = splitter.split(
        "# Gamma\n" + "a long sentence. " * 8,
        "md", ChunkConfig(28, 4), {"filePath": "long.md"},
    )
    assert len(subchunks) > 1
    assert all(json.loads(chunk.metadata)["heading"] == "# Gamma" for chunk in subchunks)
    assert all(len(chunk.content) <= 28 for chunk in subchunks)


def test_text_splitter_handles_structured_and_code_inputs():
    splitter = TextSplitter()
    json_chunks = splitter.split('{"z": 1, "a": 2}', "json", ChunkConfig(100, 0))
    csv_chunks = splitter.split("name,value\nalpha, 1", "csv", ChunkConfig(100, 0))
    malformed_json = splitter.split("{broken", "json", ChunkConfig(100, 0))
    code = splitter.split(
        "def first():\n    return 1\n\nclass Second:\n    pass",
        "py", ChunkConfig(100, 0), {"filePath": "module.py"},
    )

    assert '"a": 2' in json_chunks[0].content and '"z": 1' in json_chunks[0].content
    assert csv_chunks[0].content == "name | value\nalpha | 1"
    assert malformed_json[0].content == "{broken"
    assert [chunk.chunk_type for chunk in code] == ["code", "code"]
    assert json.loads(code[0].metadata)["filePath"] == "module.py"
    assert splitter.split(" \n", "txt", ChunkConfig(8, 0)) == []


def test_embedding_serialization_and_similarity_validate_vectors():
    encoded = serialize_embedding([0.25, -0.5])

    assert encoded == struct.pack("<2f", 0.25, -0.5)
    assert deserialize_embedding(encoded) == pytest.approx([0.25, -0.5])
    assert serialize_embedding([]) == b""
    assert deserialize_embedding(b"") == []
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([0, 0], [1, 0]) == 0.0
    assert cosine_similarity([1], [1, 0]) == 0.0


def test_embedder_uses_dispatch_and_rejects_http_and_dimension_errors(monkeypatch):
    import httpx

    class Client:
        def __init__(self, **_kwargs):
            self.response = SimpleNamespace(status_code=200, text="", json=lambda: {
                "data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}],
            })
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self.response

    clients = []

    def create_client(**kwargs):
        client = Client(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", create_client)
    channel = SimpleNamespace(type="openai", api_key="secret", base_url="https://embed.test/v1")
    dispatcher = SimpleNamespace(dispatch=lambda _model: SimpleNamespace(
        channel=channel, upstream_model="provider-embed",
    ))
    embedder = EmbedderService(dispatcher, None)

    assert embedder.embed_batch([], "embed") == []
    assert embedder.embed_batch(["one", "two"], "embed") == [[1.0, 0.0], [0.0, 1.0]]
    url, request = clients[0].calls[0]
    assert url == "https://embed.test/v1/embeddings"
    assert request["json"] == {"model": "provider-embed", "input": ["one", "two"]}
    assert request["headers"]["Authorization"] == "Bearer secret"

    clients[0].response = SimpleNamespace(
        status_code=200, text="", json=lambda: {"data": [
            {"embedding": [1.0]}, {"embedding": [1.0, 2.0]},
        ]},
    )
    with pytest.raises(ValueError, match="dimension mismatch"):
        embedder.embed_batch(["one", "two"], "embed")
    clients[0].response = SimpleNamespace(status_code=503, text="unavailable", json=dict)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        embedder.embed_batch(["one"], "embed")


def test_embedder_uses_anthropic_headers_and_single_text_helper(monkeypatch):
    import httpx

    calls = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"data": [{"embedding": [0.1, 0.2]}]},
            )

    monkeypatch.setattr(httpx, "Client", Client)
    channel = SimpleNamespace(type="claude", api_key="anthropic-key", base_url="https://embed.test")
    embedder = EmbedderService(
        SimpleNamespace(dispatch=lambda _model: SimpleNamespace(
            channel=channel, upstream_model="embedding-model",
        )), None,
    )

    assert embedder.embed("  ", "model") == []
    assert embedder.embed("text", "model") == pytest.approx([0.1, 0.2])
    assert calls[0][1]["headers"]["x-api-key"] == "anthropic-key"
    assert calls[0][1]["headers"]["anthropic-version"] == "2023-06-01"


class RecordingKnowledgeRepository:
    def __init__(self, chunks):
        self.chunks = chunks
        self.fulltext_calls = []
        self.index_status = "ready"

    def find_kb_by_id(self, _kb_id):
        return SimpleNamespace(index_status=self.index_status)

    def find_chunk_by_kb_id(self, _kb_id):
        return self.chunks

    def fulltext_search(self, kb_id, query, top_k):
        self.fulltext_calls.append((kb_id, query, top_k))
        return self.chunks[:top_k]


class StaticIndex:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def search_with_index(self, kb_id, vector, top_k):
        self.calls.append((kb_id, vector, top_k))
        if self.error:
            raise self.error
        return self.results


def test_retriever_vector_scan_and_hnsw_index_fallback():
    chunks = [
        KbChunkEntity(id="c1", doc_id="d1", content="one", embedding=struct.pack("<2f", 1, 0)),
        KbChunkEntity(id="c2", doc_id="d2", content="two", embedding=struct.pack("<2f", 0, 1)),
        KbChunkEntity(id="c3", doc_id="d3", content="no vector"),
    ]
    repository = RecordingKnowledgeRepository(chunks)
    index = StaticIndex(error=ValueError("bad index"))
    retriever = RetrieverService(repository, object(), index)

    results = retriever.vector_search("kb-1", [1.0, 0.0], 5)

    assert [result.chunk_id for result in results] == ["c1", "c2"]
    assert [result.score for result in results] == [1.0, 0.0]
    assert index.calls == [("kb-1", [1.0, 0.0], 5)]
    repository.index_status = "ready"
    index.error = None
    index.results = [{"chunk_id": "c-index", "score": 0.8, "metadata": None}]
    indexed = retriever.vector_search("kb-1", [1.0, 0.0], 2)
    assert indexed[0].chunk_id == "c-index" and indexed[0].metadata == {}


def test_retriever_keyword_deduplicates_and_falls_back_to_like():
    first = KbChunkEntity(id="c1", doc_id="d1", content="Alpha beta", metadata="invalid")
    repository = RecordingKnowledgeRepository([first, first])
    retriever = RetrieverService(repository, object(), StaticIndex())

    results = retriever.keyword_search("kb-1", "Alpha beta", 5)
    assert len(results) == 1 and results[0].metadata == {}
    assert repository.fulltext_calls == [("kb-1", "+Alpha* +beta*", 5)]
    assert retriever.keyword_search("kb-1", "!!!", 5) == []

    repository.fulltext_search = lambda *_args: (_ for _ in ()).throw(RuntimeError("fts unavailable"))
    fallback = retriever.keyword_search("kb-1", "alpha", 5)
    assert fallback[0].chunk_id == "c1"


def test_retriever_hybrid_merges_scores_and_cjk_query_terms():
    vector = SearchResultEntity(chunk_id="same", doc_id="d1", score=0.8)
    other = SearchResultEntity(chunk_id="vector-only", doc_id="d2", score=0.4)
    keyword = SearchResultEntity(chunk_id="same", doc_id="d1", score=1.0)
    new = SearchResultEntity(chunk_id="keyword-only", doc_id="d3", score=1.0)

    class Retriever(RetrieverService):
        def vector_search(self, *_args):
            return [vector, other]

        def keyword_search(self, *_args):
            return [keyword, new]

    retriever = Retriever(RecordingKnowledgeRepository([]), object(), StaticIndex())
    merged = retriever.hybrid_search("kb", "q", [1], 5, 0.5, 0.25)

    assert [(item.chunk_id, item.score) for item in merged] == [
        ("same", 0.65), ("keyword-only", 0.25), ("vector-only", 0.2),
    ]
    assert retriever._build_fts_query("你好 hello!") == "+你好* +hello*"


def test_rag_context_builder_trims_context_and_selects_model_limits():
    builder = RagContextBuilder()
    result = SearchResultEntity(
        doc_id="doc-1", content="facts", metadata={"filePath": "guide.md", "heading": "Start"},
    )

    context = builder.build_context([result])
    prompt = builder.build_rag_prompt(context, "question", [{"role": "user", "content": "previous"}])
    trimmed = builder.trim_context("x" * 10_000, 1000)

    assert "guide.md" in context and "Start" in context and "facts" in context
    assert "previous" in prompt and "question" in prompt
    assert "裁剪" in trimmed and len(trimmed) < 10_000
    assert builder.trim_context("", 1000) == ""
    assert builder.get_model_context_limit("gpt-4-128k") == 128000
    assert builder.get_model_context_limit("claude-3") == 200000
    assert builder.get_model_context_limit(None) == 4096


class RecordingGateway:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.requests = []

    def forward_sync(self, request):
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return ProxyResponseEntity(
            body=json.dumps({"choices": [{"message": {"content": "answer"}}]}),
            prompt_tokens=2, completion_tokens=3, total_tokens=5,
        )


def _response(content, success=True, error=None):
    return ProxyResponseEntity(
        success=success,
        body=json.dumps({"choices": [{"message": {"content": content}}]}) if content else "",
        error_message=error,
        prompt_tokens=2,
        completion_tokens=3,
        total_tokens=5,
    )


def test_rag_vector_and_hybrid_modes_fall_back_to_keyword():
    result = SearchResultEntity(chunk_id="c1", doc_id="d1", content="answer")

    class Retriever:
        def __init__(self, failure=None):
            self.failure = failure
            self.calls = []

        def vector_search(self, *_args):
            self.calls.append("vector")
            if self.failure:
                raise self.failure
            return []

        def hybrid_search(self, *_args):
            self.calls.append("hybrid")
            return []

        def keyword_search(self, *_args):
            self.calls.append("keyword")
            return [result]

    retriever = Retriever()
    rag = RagService(retriever, SimpleNamespace(embed=lambda *_args: [1]), RecordingGateway(), RagContextBuilder())
    assert rag.search_by_mode("kb", "q", 3, "vector", "embed") == [result]
    assert retriever.calls == ["vector", "keyword"]
    retriever.calls.clear()
    assert rag.search_by_mode("kb", "q", 3, "hybrid", "embed") == [result]
    assert retriever.calls == ["hybrid", "keyword"]
    retriever.calls.clear()
    retriever.failure = RuntimeError("vector failure")
    assert rag.search_by_mode("kb", "q", 3, "vector", "embed") == [result]
    assert retriever.calls == ["vector", "keyword"]


def test_rag_ask_builds_source_usage_and_handles_upstream_errors():
    result = SearchResultEntity(
        chunk_id="c1", doc_id="d1", content="x" * 220, score=0.9,
        metadata={"filePath": "guide.md"},
    )

    class Retriever:
        def keyword_search(self, *_args):
            return [result]

    gateway = RecordingGateway([_response("grounded"), _response(None, False, "upstream down")])
    rag = RagService(Retriever(), SimpleNamespace(embed=lambda *_args: [1]), gateway, RagContextBuilder())

    answer = rag.ask("kb", "question", "embed", "chat", 2, [{"role": "user", "content": "history"}])
    failed = rag.ask("kb", "question", "embed", "chat", 2)

    assert answer.answer == "grounded"
    assert answer.sources[0]["filename"] == "guide.md"
    assert len(answer.sources[0]["snippet"]) == 203
    assert answer.usage == {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    assert gateway.requests[0].body["messages"][0] == {"role": "user", "content": "history"}
    assert failed.answer.endswith("upstream down")


def test_rag_deep_research_deduplicates_sources_and_stops_at_round_limit():
    result = SearchResultEntity(chunk_id="same", doc_id="d1", content="evidence")

    class Retriever:
        def __init__(self):
            self.queries = []

        def keyword_search(self, _kb, query, _top_k):
            self.queries.append(query)
            return [result]

    retriever = Retriever()
    gateway = RecordingGateway([
        _response("first answer"), _response("follow-up?"),
        _response("second answer"), _response(""),
    ])
    rag = RagService(retriever, SimpleNamespace(embed=lambda *_args: [1]), gateway, RagContextBuilder())

    answer = rag.deep_research("kb", "question", "embed", "chat", 5, max_rounds=2)

    assert answer.answer == "first answer\n\nsecond answer"
    assert retriever.queries == ["question", "follow-up?"]
    assert len(answer.sources) == 1
    assert len(gateway.requests) == 4

