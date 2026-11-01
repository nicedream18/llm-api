import struct

import pytest

from app.application.errors import ApplicationError
from app.domain.entities import KbChunkEntity, KbKnowledgeBaseEntity
from app.domain.importer import ImporterService


class FakeRepository:
    def __init__(self):
        self.kb = KbKnowledgeBaseEntity(
            id="kb-1", embedding_model="embed-v1", index_status="ready"
        )
        self.sources = {}
        self.documents = {}
        self.chunks = []

    def save_source(self, kb_id, source_type, **values):
        source_id = values["source_id"]
        self.sources[source_id] = {
            "kb_id": kb_id,
            "source_type": source_type,
            **values,
        }

    def update_source_status(self, source_id, status, error=None, file_count=None):
        self.sources[source_id].update(
            status=status, error=error, file_count=file_count
        )

    def save_doc(self, document):
        self.documents[document.id] = document

    def update_doc_status(self, doc_id, status, error):
        self.documents[doc_id].status = status
        self.documents[doc_id].error_message = error

    def update_doc(self, document):
        self.documents[document.id] = document

    def save_chunk_batch(self, chunks):
        self.chunks.extend(chunks)

    def find_kb_by_id(self, _kb_id):
        return self.kb

    def find_doc_by_kb_id(self, _kb_id):
        return list(self.documents.values())

    def find_chunk_by_kb_id(self, _kb_id):
        return self.chunks

    def update_kb(self, kb):
        self.kb = kb


class FakeSplitter:
    def __init__(self):
        self.calls = []

    def split(self, content, file_type, config, metadata):
        self.calls.append((content, file_type, config, metadata))
        return [
            KbChunkEntity(
                id="chunk-1", content=content, chunk_index=0, token_count=3
            )
        ]


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def embed_batch(self, contents, model):
        self.calls.append((contents, model))
        return [[0.25, 0.75] for _ in contents]


def make_importer():
    repository = FakeRepository()
    splitter = FakeSplitter()
    embedder = FakeEmbedder()
    importer = ImporterService(repository, splitter, embedder)
    return importer, repository, splitter, embedder


def test_local_directory_import_ingests_files_and_refreshes_kb_stats(tmp_path):
    (tmp_path / "guide.md").write_text("A useful guide", encoding="utf-8")
    (tmp_path / "ignored.bin").write_bytes(b"binary")
    ignored_dir = tmp_path / "node_modules"
    ignored_dir.mkdir()
    (ignored_dir / "skip.md").write_text("ignored", encoding="utf-8")
    importer, repository, splitter, embedder = make_importer()

    result = importer.import_source(
        "kb-1", {"sourceType": "local_dir", "dirPath": str(tmp_path)}
    )

    source = repository.sources[result["sourceId"]]
    document = next(iter(repository.documents.values()))
    chunk = repository.chunks[0]
    assert result["success"] is True and result["totalChunks"] == 1
    assert source["status"] == "ingested" and source["file_count"] == 1
    assert document.name == "guide.md" and document.status == "ready"
    assert chunk.kb_id == "kb-1" and chunk.doc_id == document.id
    assert struct.unpack("<2f", chunk.embedding) == pytest.approx((0.25, 0.75))
    assert splitter.calls[0][0:2] == ("A useful guide", "md")
    assert splitter.calls[0][3] == {"filePath": "guide.md"}
    assert embedder.calls == [(["A useful guide"], "embed-v1")]
    assert (repository.kb.doc_count, repository.kb.chunk_count,
            repository.kb.total_tokens, repository.kb.index_status) == (1, 1, 3, "stale")


def test_local_directory_import_records_failure_and_preserves_error(tmp_path):
    importer, repository, *_ = make_importer()
    missing = tmp_path / "does-not-exist"

    with pytest.raises(ApplicationError, match="Directory does not exist"):
        importer.import_source(
            "kb-1", {"sourceType": "local_dir", "dirPath": str(missing)}
        )

    source = next(iter(repository.sources.values()))
    assert source["status"] == "failed"
    assert source["error"] == "Directory does not exist"
    assert source["file_count"] == 0
    assert repository.kb.index_status == "ready"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "sourceType is required"),
        ({"source_type": "unknown"}, "Unsupported source type: unknown"),
    ],
)
def test_importer_rejects_missing_or_unknown_source_type_without_persisting(body, message):
    importer, repository, *_ = make_importer()

    result = importer.import_source("kb-1", body)

    assert result == {"success": False, "message": message}
    assert repository.sources == {}
