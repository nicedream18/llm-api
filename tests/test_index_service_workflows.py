import struct

from app.domain.entities import KbChunkEntity
from app.domain.index_service import IndexService


class FakeRepository:
    def __init__(self, chunks):
        self.chunks = chunks
        self.metadata = {}
        self.metadata_updates = []

    def find_chunk_by_kb_id(self, _kb_id):
        return self.chunks

    def upsert_index_meta(self, kb_id, key, value):
        self.metadata[(kb_id, key)] = value
        self.metadata_updates.append((kb_id, key, value))

    def find_index_meta_by_kb_id(self, kb_id):
        return {
            key: value
            for (stored_kb_id, key), value in self.metadata.items()
            if stored_kb_id == kb_id
        }


def test_build_search_and_drop_index_preserve_chunk_metadata(monkeypatch, tmp_path):
    chunks = [
        KbChunkEntity(
            id="chunk-1",
            doc_id="doc-1",
            content="indexed content",
            embedding=struct.pack("<2f", 1.0, 0.0),
            metadata='{"filePath":"manual/guide.md","page":2}',
        ),
        KbChunkEntity(
            id="chunk-2",
            doc_id="doc-2",
            content="missing vector",
            embedding=None,
        ),
    ]
    repository = FakeRepository(chunks)
    monkeypatch.setattr("app.domain.index_service.INDEX_DIR", str(tmp_path))
    service = IndexService(repository)

    result = service.build_index("kb-1")

    assert result["success"] is True
    assert result["totalChunks"] == 2
    assert result["indexedChunks"] == 1 and result["skipped"] == 1
    assert repository.metadata[("kb-1", "status")] == "ready"
    assert repository.metadata[("kb-1", "embedding_dim")] == "2"
    assert service.get_index_status("kb-1")["chunk_count"] == "1"

    results = service.search_with_index("kb-1", [1.0, 0.0], 5)
    assert results == [
        {
            "chunk_id": "chunk-1",
            "doc_id": "doc-1",
            "filename": "manual/guide.md",
            "content": "indexed content",
            "score": 1.0,
            "metadata": {"filePath": "manual/guide.md", "page": 2},
        }
    ]
    assert service.search_with_index("kb-1", [1.0], 5) == []

    dropped = service.drop_index("kb-1")
    assert dropped == {"success": True, "fileDeleted": True}
    assert not (tmp_path / "kb-1.index").exists()
    assert repository.metadata[("kb-1", "status")] == "none"
    assert repository.metadata[("kb-1", "chunk_count")] == "0"


def test_build_index_reports_empty_and_unusable_embeddings(monkeypatch, tmp_path):
    monkeypatch.setattr("app.domain.index_service.INDEX_DIR", str(tmp_path))
    empty_service = IndexService(FakeRepository([]))
    invalid_service = IndexService(
        FakeRepository([KbChunkEntity(embedding=b"\x01")])
    )

    assert empty_service.build_index("empty") == {
        "success": False,
        "message": "没有可索引的分块",
    }
    assert invalid_service.build_index("invalid") == {
        "success": False,
        "message": "没有有效的嵌入向量（需要先调用 Embedder 生成向量）",
    }
    assert list(tmp_path.iterdir()) == []


def test_index_metadata_parser_handles_non_object_json():
    assert IndexService._parse_metadata('["not", "an", "object"]') == {}
    assert IndexService._parse_metadata("invalid json") == {}
    assert IndexService._extract_filename(
        KbChunkEntity(doc_id="doc-fallback", metadata='["bad shape"]')
    ) == "doc-fallback"
