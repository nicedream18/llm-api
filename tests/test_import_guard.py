import pytest

from app.application.errors import ApplicationError
from app.domain.importer import ImportGuard, file_walk


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
