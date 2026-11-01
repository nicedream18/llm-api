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
    loaded = HnswIndex.load(str(path))
    assert loaded and loaded.search([1.0, 0.0], 1)[0]["id"] == 1
    path.write_bytes(b"partial pickle")
    assert HnswIndex.load(str(path)) is None
    assert not list(tmp_path.glob(".hnsw-*.tmp"))


def test_index_service_skips_mixed_dimensions_and_rejects_unsafe_ids(monkeypatch, tmp_path):
    class Repo:
        def find_chunk_by_kb_id(self, _kb_id):
            return [
                type("Chunk", (), {"embedding": struct.pack("<2f", 1, 0)})(),
                type("Chunk", (), {"embedding": struct.pack("<3f", 1, 0, 0)})(),
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
