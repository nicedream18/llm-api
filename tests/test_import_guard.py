import pytest

from app.application.errors import ApplicationError
from app.domain.importer import ImporterService, ImportGuard, file_walk
from app.domain.knowledge import ChunkConfig, TextSplitter


def test_local_file_walk_skips_unsupported_and_counts_content(tmp_path):
    (tmp_path / "guide.md").write_text("hello", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"binary")
    seen = []
    assert file_walk(str(tmp_path), handler=lambda name, path, content: seen.append((name, path, content)) or 1) == 1
    assert seen == [("guide.md", "guide.md", "hello")]


def test_file_walk_rejects_file_count_limit(tmp_path):
    for index in range(3):
        (tmp_path / f"{index}.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ApplicationError, match="too many files"):
        file_walk(str(tmp_path), handler=lambda *_: 1, max_files=2)


def test_file_walk_rejects_total_size_limit(tmp_path):
    (tmp_path / "large.txt").write_text("12345", encoding="utf-8")
    with pytest.raises(ApplicationError, match="total size"):
        file_walk(str(tmp_path), handler=lambda *_: 1, max_total_bytes=4)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://127.0.0.1/private",
    "http://localhost/private",
    "https://user:password@example.com/docs",
])
def test_remote_url_rejects_unsafe_targets(url):
    with pytest.raises(ApplicationError):
        ImportGuard.remote_url(url)


def test_remote_url_accepts_public_ip():
    assert ImportGuard.remote_url("https://8.8.8.8/docs") == "https://8.8.8.8/docs"


def test_branch_rejects_option_injection_and_path_traversal():
    with pytest.raises(ApplicationError):
        ImportGuard.branch("--upload-pack=evil")
    with pytest.raises(ApplicationError):
        ImportGuard.branch("feature/../main")


def test_text_splitter_normalizes_json_and_extracts_code_symbols():
    splitter = TextSplitter()
    json_chunks = splitter.split('{"b": 2, "a": 1}', "json", ChunkConfig(512, 0), {"filePath": "data.json"})
    assert '"b": 2' in json_chunks[0].content and '"a": 1' in json_chunks[0].content
    code_chunks = splitter.split("def first():\n    return 1\n\nclass Second:\n    pass", "py", ChunkConfig(512, 0), {"filePath": "a.py"})
    assert [chunk.chunk_type for chunk in code_chunks] == ["code", "code"]
    assert code_chunks[0].language == "py"


def test_importer_persists_returned_source_id_and_failure_status():
    class Repo:
        def __init__(self):
            self.sources = {}
            self.updates = []
        def save_source(self, kb_id, source_type, **kwargs):
            self.sources[kwargs["source_id"]] = {"kb_id": kb_id, "source_type": source_type, "status": kwargs["status"]}
        def update_source_status(self, source_id, status, error=None, file_count=None):
            self.updates.append((source_id, status, file_count))
            self.sources[source_id].update(status=status, error=error)

    repo = Repo()
    importer = ImporterService(repo, TextSplitter(), object())
    importer.strategies["test"] = type("Failing", (), {
        "get_source_type": lambda self: "test",
        "import_source": lambda self, *_args: 0,
    })()
    result = importer.import_source("kb-1", {"source_type": "test"})
    assert result["sourceId"] in repo.sources
    assert repo.sources[result["sourceId"]]["status"] == "failed"
    assert repo.updates[-1] == (result["sourceId"], "failed", 0)


def test_importer_persists_source_file_count():
    class Repo:
        def __init__(self):
            self.updates = []

        def save_source(self, _kb_id, _source_type, **_kwargs):
            pass

        def update_source_status(self, source_id, status, error=None, file_count=None):
            self.updates.append((source_id, status, error, file_count))

    repo = Repo()
    importer = ImporterService(repo, TextSplitter(), object())
    importer.strategies["test"] = type("Successful", (), {
        "get_source_type": lambda self: "test",
        "import_source": lambda self, _kb_id, _source_id, context, _params: setattr(context, "file_count", 3) or 4,
    })()

    result = importer.import_source("kb-1", {"source_type": "test"})

    assert result["totalChunks"] == 4
    assert repo.updates[-1] == (result["sourceId"], "ingested", None, 3)


def test_importer_refreshes_kb_counts_and_invalidates_index():
    class Repo:
        def __init__(self):
            from app.domain.entities import KbKnowledgeBaseEntity

            self.kb = KbKnowledgeBaseEntity(id="kb-1", index_status="ready")
            self.docs = [type("Doc", (), {"status": "ready", "total_tokens": 12})()]
            self.chunks = [object(), object()]
            self.source = None

        def save_source(self, _kb_id, _source_type, **_kwargs):
            pass

        def update_source_status(self, _source_id, _status, _error=None, _file_count=None):
            pass

        def find_kb_by_id(self, _kb_id):
            return self.kb

        def find_doc_by_kb_id(self, _kb_id):
            return self.docs

        def find_chunk_by_kb_id(self, _kb_id):
            return self.chunks

        def update_kb(self, kb):
            self.kb = kb

    repo = Repo()
    importer = ImporterService(repo, TextSplitter(), object())
    importer.strategies["test"] = type("Successful", (), {
        "get_source_type": lambda self: "test",
        "import_source": lambda self, _kb_id, _source_id, context, _params: setattr(context, "file_count", 2) or 4,
    })()

    importer.import_source("kb-1", {"source_type": "test"})

    assert (repo.kb.doc_count, repo.kb.chunk_count, repo.kb.total_tokens) == (1, 2, 12)
    assert repo.kb.index_status == "stale"
