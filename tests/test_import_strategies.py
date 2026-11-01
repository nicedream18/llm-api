from contextlib import contextmanager

import httpx
import pytest

from app.application.errors import ApplicationError
from app.domain import importer as importer_module
from app.domain.importer import (
    GitImportStrategy,
    ImportContext,
    ImportParams,
    UrlImportStrategy,
)


class ImportRepository:
    def __init__(self):
        self.docs = []
        self.chunks = []
        self.source_updates = []

    def save_doc(self, doc):
        self.docs.append(doc)

    def save_chunk_batch(self, chunks):
        self.chunks.extend(chunks)

    def update_doc_status(self, *_args):
        pass

    def update_doc(self, _doc):
        pass

    def find_kb_by_id(self, _kb_id):
        return None

    def update_source_status(self, *args):
        self.source_updates.append(args)


class ImportSplitter:
    def split(self, content, _file_type, _config, _metadata):
        from app.domain.entities import KbChunkEntity

        return [KbChunkEntity(content=content, token_count=2)]


class EmptyEmbedder:
    def embed_batch(self, _content, _model):
        return []


class Response:
    def __init__(self, status, body=b"", headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.body = body

    def iter_bytes(self):
        yield self.body


def _context():
    repo = ImportRepository()
    return ImportContext(repo, ImportSplitter(), EmptyEmbedder()), repo


def _install_responses(monkeypatch, responses):
    requests = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @contextmanager
        def stream(self, method, url, **kwargs):
            requests.append((method, url, kwargs))
            response = responses.pop(0)
            yield response

    monkeypatch.setattr(importer_module.httpx, "Client", Client)
    return requests


def test_url_import_revalidates_redirects_and_uses_final_url(monkeypatch):
    context, repo = _context()
    checks = []
    monkeypatch.setattr(importer_module.ImportGuard, "remote_url", lambda url: checks.append(url) or url)
    requests = _install_responses(monkeypatch, [
        Response(302, headers={"location": "/manuals/guide.md"}),
        Response(200, b"useful contents"),
    ])

    count = UrlImportStrategy().import_source(
        "kb-1", "source-1", context, ImportParams(url="https://docs.example/redirect")
    )

    assert count == 1
    assert [item[1] for item in requests] == [
        "https://docs.example/redirect", "https://docs.example/manuals/guide.md",
    ]
    assert checks == [
        "https://docs.example/redirect",
        "https://docs.example/redirect",
        "https://docs.example/manuals/guide.md",
    ]
    assert repo.docs[0].name == "guide.md"
    assert repo.docs[0].source_path == "https://docs.example/manuals/guide.md"
    assert repo.source_updates == [("source-1", "ingested", None, 1)]
    assert requests[0][2]["headers"]["User-Agent"] == "WaLiAPI/1.0"


@pytest.mark.parametrize(
    ("responses", "message"),
    [
        ([Response(301)], "no destination"),
        ([Response(302, headers={"location": "/one"})] * 5, "Too many redirects"),
    ],
)
def test_url_import_rejects_missing_and_excessive_redirects(monkeypatch, responses, message):
    context, _repo = _context()
    monkeypatch.setattr(importer_module.ImportGuard, "remote_url", lambda url: url)
    _install_responses(monkeypatch, responses)

    with pytest.raises(ApplicationError, match=message):
        UrlImportStrategy().import_source(
            "kb-1", "source-1", context, ImportParams(url="https://docs.example/start")
        )


def test_url_import_checks_redirect_targets_and_response_size(monkeypatch):
    context, _repo = _context()
    checked = []

    def check_url(url):
        checked.append(url)
        if url.startswith("http://127."):
            raise ApplicationError("Private redirect blocked", 422, "ssrf_blocked")
        return url

    monkeypatch.setattr(importer_module.ImportGuard, "remote_url", check_url)
    _install_responses(monkeypatch, [Response(302, headers={"location": "http://127.0.0.1/private"})])
    with pytest.raises(ApplicationError, match="Private redirect blocked"):
        UrlImportStrategy().import_source(
            "kb-1", "source-1", context, ImportParams(url="https://docs.example/start")
        )

    monkeypatch.setattr(importer_module.ImportGuard, "remote_url", lambda url: url)
    monkeypatch.setattr(importer_module, "MAX_URL_BYTES", 3)
    _install_responses(monkeypatch, [Response(200, b"four")])
    with pytest.raises(ApplicationError, match="size limit"):
        UrlImportStrategy().import_source(
            "kb-1", "source-2", context, ImportParams(url="https://docs.example/file.txt")
        )


def test_url_import_returns_zero_for_http_errors_and_non_success_status(monkeypatch):
    context, _repo = _context()
    monkeypatch.setattr(importer_module.ImportGuard, "remote_url", lambda url: url)
    requests = _install_responses(monkeypatch, [Response(503)])
    assert UrlImportStrategy().import_source(
        "kb-1", "source-1", context, ImportParams(url="https://docs.example/file.txt")
    ) == 0
    assert len(requests) == 1

    class BrokenClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            raise httpx.ConnectError("secret", request=httpx.Request("GET", "https://docs.example"))

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(importer_module.httpx, "Client", BrokenClient)
    assert UrlImportStrategy().import_source(
        "kb-1", "source-2", context, ImportParams(url="https://docs.example/file.txt")
    ) == 0


def test_git_import_uses_header_auth_and_cleans_temp_directory(monkeypatch, tmp_path):
    context, repo = _context()
    temp_dir = str(tmp_path / "clone")
    calls = []
    cleaned = []
    monkeypatch.setattr(importer_module.tempfile, "mkdtemp", lambda **_kwargs: temp_dir)
    monkeypatch.setattr(importer_module.ImportGuard, "remote_url", lambda url: url)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert "secret-token" not in command
        assert kwargs["env"]["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer secret-token"
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    def walk(_root, _excluded, _included, _max_size, handler):
        return handler("README.md", "README.md", "hello")

    monkeypatch.setattr(importer_module.subprocess, "run", run)
    monkeypatch.setattr(importer_module, "file_walk", walk)
    monkeypatch.setattr(importer_module, "delete_directory", cleaned.append)

    result = GitImportStrategy().import_source(
        "kb-1", "source-1", context,
        ImportParams(repo_url="https://git.example/repo", branch="main", token="secret-token"),
    )

    assert result == 1
    assert calls[0][0][:6] == ["git", "clone", "--depth", "1", "--branch", "main"]
    assert cleaned == [temp_dir]
    assert repo.docs[0].source_type == "git"
    assert repo.source_updates == [("source-1", "ingested", None, 1)]


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_git_import_failures_return_zero_and_always_clean_clone(monkeypatch, tmp_path, failure):
    context, _repo = _context()
    temp_dir = str(tmp_path / "clone")
    cleaned = []
    monkeypatch.setattr(importer_module.tempfile, "mkdtemp", lambda **_kwargs: temp_dir)
    monkeypatch.setattr(importer_module.ImportGuard, "remote_url", lambda url: url)
    monkeypatch.setattr(importer_module, "delete_directory", cleaned.append)
    if failure == "exit":
        monkeypatch.setattr(importer_module.subprocess, "run", lambda *_args, **_kwargs: type("Result", (), {"returncode": 1, "stderr": "failed"})())
    else:
        monkeypatch.setattr(importer_module.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(importer_module.subprocess.TimeoutExpired("git", 1)))

    assert GitImportStrategy().import_source(
        "kb-1", "source-1", context,
        ImportParams(repo_url="https://git.example/repo"),
    ) == 0
    assert cleaned == [temp_dir]
