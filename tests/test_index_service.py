import pickle
import struct

import pytest

from app.domain.index_service import HnswIndex, IndexService


def test_hnsw_rejects_invalid_dimensions_and_values():
    with pytest.raises(ValueError):
        HnswIndex(0)
    index = HnswIndex(2)
    with pytest.raises(ValueError):
        index.build([1], [[1.0]])
    with pytest.raises(ValueError):
        index.build([1], [[1.0, float("nan")]])
    index.build([1], [[1.0, 2.0]])
    with pytest.raises(ValueError):
        index.search([1.0], 1)


def test_hnsw_save_is_atomic_and_corrupt_files_are_ignored(tmp_path):
    path = tmp_path / "demo.index"
    index = HnswIndex(2)
    index.build([1, 2], [[1.0, 0.0], [0.0, 1.0]])
    index.save(str(path))
    assert path.read_bytes().startswith(b'{"format":"waliapi-hnsw"')
    loaded = HnswIndex.load(str(path))
    assert loaded and loaded.search([1.0, 0.0], 1)[0]["id"] == 1
    path.write_bytes(b"partial pickle")
    assert HnswIndex.load(str(path)) is None
    assert not list(tmp_path.glob(".hnsw-*.tmp"))


def test_hnsw_loader_rejects_invalid_graph_references(tmp_path):
    path = tmp_path / "invalid.index"
    path.write_text('{"format":"waliapi-hnsw","format_version":1,"dim":1,"max_m":1,"ef_construction":1,"ef_search":1,"entry_point":0,"initialized":true,"nodes":[{"id":0,"vector":[1.0],"neighbours":[4]}]}', encoding="utf-8")

    assert HnswIndex.load(str(path)) is None


def test_hnsw_loader_does_not_execute_legacy_pickle_payload(tmp_path):
    marker = tmp_path / "pickle-executed.txt"
    path = tmp_path / "legacy.index"

    class Payload:
        def __reduce__(self):
            return (type(marker).write_text, (marker, "executed"))

    path.write_bytes(pickle.dumps(Payload()))

    assert HnswIndex.load(str(path)) is None
    assert not marker.exists()


def test_index_service_skips_mixed_dimensions_and_rejects_unsafe_ids(monkeypatch, tmp_path):
    class Repo:
        def find_chunk_by_kb_id(self, _kb_id):
            return [
                type("Chunk", (), {"id":"a", "doc_id":"d", "content":"text", "metadata":None, "embedding": struct.pack("<2f", 1, 0)})(),
                type("Chunk", (), {"id":"b", "doc_id":"d", "content":"text", "metadata":None, "embedding": struct.pack("<3f", 1, 0, 0)})(),
            ]

        def upsert_index_meta(self, *_args):
            return None

    monkeypatch.setattr("app.domain.index_service.INDEX_DIR", str(tmp_path))
    service = IndexService(Repo())
    result = service.build_index("kb_1")
    assert result["success"] is True
    assert result["indexedChunks"] == 1
    with pytest.raises(ValueError):
        service.build_index("../outside")
