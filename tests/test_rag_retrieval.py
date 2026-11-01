
from app.domain.entities import ProxyResponseEntity, SearchResultEntity
from app.domain.knowledge import RagContextBuilder, RagService


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
