"""Importer strategy system for knowledge base (aligned with Java importer/strategy package)."""
import ipaddress
import logging
import os
import shutil
import socket
import subprocess
import tempfile
from datetime import UTC
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.application.errors import ApplicationError
from app.domain.entities import KbChunkEntity, KbDocumentEntity
from app.domain.knowledge import ChunkConfig, serialize_embedding

logger = logging.getLogger(__name__)


# ============================================================
# FileWalker (aligned with Java FileWalker.java)
# ============================================================

IGNORED_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "target", "build", "dist",
    "__pycache__", ".idea", ".vscode", ".gradle", "out", "bin",
}

SUPPORTED_EXTS = {
    "md", "markdown", "txt", "rst",
    "java", "kt", "scala", "py", "rs", "go", "c", "cpp", "h", "hpp",
    "ts", "tsx", "js", "jsx", "mjs",
    "cs", "rb", "php", "swift", "dart",
    "sh", "bash", "sql", "lua",
    "json", "yaml", "yml", "xml", "csv", "toml", "ini", "properties",
}

DEFAULT_MAX_FILE_SIZE = 512 * 1024  # 512KB
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_URL_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3


class ImportGuard:
    """Validate filesystem and remote import boundaries before reading data."""

    @staticmethod
    def local_root(root_path: str) -> Path:
        if not root_path:
            raise ApplicationError("Directory path is required", 422, "invalid_import_path")
        raw = Path(root_path).expanduser()
        if raw.is_symlink():
            raise ApplicationError("Symbolic-link roots are not allowed", 422, "invalid_import_path")
        try:
            root = raw.resolve(strict=True)
        except OSError as exc:
            raise ApplicationError("Directory does not exist", 422, "invalid_import_path") from exc
        if not root.is_dir():
            raise ApplicationError("Directory does not exist", 422, "invalid_import_path")
        return root

    @staticmethod
    def file_path(root: Path, candidate: Path) -> tuple[Path, int]:
        if candidate.is_symlink():
            raise ApplicationError("Symbolic-link files are not allowed", 422, "invalid_import_path")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            size = resolved.stat().st_size
        except (OSError, ValueError) as exc:
            raise ApplicationError("Import path is outside the selected directory", 422, "invalid_import_path") from exc
        if not resolved.is_file():
            raise ApplicationError("Import path is not a regular file", 422, "invalid_import_path")
        return resolved, size

    @staticmethod
    def remote_url(url: str) -> str:
        parsed = urlparse(url or "")
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ApplicationError("Only http and https import URLs are allowed", 422, "invalid_import_url")
        if parsed.username or parsed.password:
            raise ApplicationError("Import URLs cannot contain credentials", 422, "invalid_import_url")
        host = parsed.hostname
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                addresses = [item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)]
            except (OSError, socket.gaierror) as exc:
                raise ApplicationError("Import URL host could not be resolved", 422, "invalid_import_url") from exc
        for address in set(addresses):
            try:
                ip = ipaddress.ip_address(address)
            except ValueError as exc:
                raise ApplicationError("Import URL resolved to an invalid address", 422, "invalid_import_url") from exc
            if not ip.is_global:
                raise ApplicationError("Private or local import URLs are not allowed", 422, "ssrf_blocked")
        return url

    @staticmethod
    def branch(branch: str | None) -> str:
        value = branch or "main"
        if len(value) > 256 or value.startswith("-") or ".." in value or any(char.isspace() for char in value):
            raise ApplicationError("Invalid Git branch", 422, "invalid_import_branch")
        return value


def file_walk(root_path: str, excluded_dirs: list[str] | None = None,
              included_files: list[str] | None = None, max_file_size: int = 0,
              handler=None, max_files: int = DEFAULT_MAX_FILES,
              max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES) -> int:
    """Walk a directory and call handler(filename, relative_path, content) for each file."""
    root = ImportGuard.local_root(root_path)

    max_size = max_file_size if max_file_size and max_file_size > 0 else DEFAULT_MAX_FILE_SIZE
    exclude_set = set(excluded_dirs or []) | IGNORED_DIRS
    include_set = set(included_files) if included_files else None

    total_chunks = 0
    file_count = 0
    total_bytes = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded dirs in-place (prunes traversal)
        dirnames[:] = [d for d in dirnames if d not in exclude_set and not (Path(dirpath) / d).is_symlink()]
        for filename in filenames:
            filepath = Path(dirpath) / filename
            if filepath.is_symlink():
                continue
            filepath, size = ImportGuard.file_path(root, filepath)
            if size > max_size:
                continue
            ext = _get_extension(filename)
            if include_set is not None:
                if ext not in include_set and filename not in include_set:
                    continue
            elif ext not in SUPPORTED_EXTS:
                continue
            file_count += 1
            total_bytes += size
            if file_count > max_files:
                raise ApplicationError("Import contains too many files", 413, "import_limit")
            if total_bytes > max_total_bytes:
                raise ApplicationError("Import exceeds total size limit", 413, "import_limit")
            try:
                with filepath.open("r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                relative_path = os.path.relpath(filepath, root)
                total_chunks += handler(filename, relative_path, content)
            except ApplicationError:
                raise
            except (OSError, UnicodeError):
                logger.warning("File processing failed: %s", filepath, exc_info=False)

    logger.info("Directory walk done: %s -> %s files, %s chunks", root_path, file_count, total_chunks)
    return total_chunks


def delete_directory(path: str):
    """Recursively delete a directory."""
    shutil.rmtree(path, ignore_errors=True)


def _get_extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot + 1:].lower() if dot >= 0 else ""


# ============================================================
# ImportParams (aligned with Java ImportParams.java)
# ============================================================

class ImportParams:
    def __init__(self, repo_url: str | None = None, branch: str | None = None, token: str | None = None,
                 url: str | None = None, dir_path: str | None = None,
                 excluded_dirs: list[str] | None = None, included_files: list[str] | None = None,
                 max_file_size: int | None = None):
        self.repo_url = repo_url
        self.branch = branch
        self.token = token
        self.url = url
        self.dir_path = dir_path
        self.excluded_dirs = excluded_dirs or []
        self.included_files = included_files
        self.max_file_size = max_file_size

    @classmethod
    def from_dict(cls, d: dict) -> "ImportParams":
        return cls(
            repo_url=d.get("repoUrl") or d.get("repo_url"),
            branch=d.get("branch"),
            token=d.get("token"),
            url=d.get("url"),
            dir_path=d.get("dirPath") or d.get("dir_path"),
            excluded_dirs=d.get("excludedDirs") or d.get("excluded_dirs") or [],
            included_files=d.get("includedFiles") or d.get("included_files"),
            max_file_size=d.get("maxFileSize") or d.get("max_file_size"),
        )


# ============================================================
# ImportContext (aligned with Java ImportContext.java)
# ============================================================

class ImportContext:
    """Shared context for import operations: document creation, chunking, embedding, persistence."""

    def __init__(self, kb_repository, text_splitter, embedder_service):
        self.repo = kb_repository
        self.splitter = text_splitter
        self.embedder = embedder_service

    def import_content(self, kb_id: str, filename: str, source_type: str,
                      source_path: str, content: str) -> int:
        """Import a single file: create doc → chunk → embed → persist."""
        import uuid
        from datetime import datetime
        now = datetime.now(UTC).isoformat()

        doc = KbDocumentEntity(
            id=str(uuid.uuid4()), kb_id=kb_id, name=filename,
            source_type=source_type, source_path=source_path,
            status="processing", chunk_count=0, total_tokens=0,
            created_at=now, updated_at=now,
        )
        self.repo.save_doc(doc)

        chunk_config = ChunkConfig()
        metadata = {"filePath": source_path}
        chunks = self.splitter.split(content, _guess_file_type(filename), chunk_config, metadata)
        for chunk in chunks:
            chunk.kb_id = kb_id
            chunk.doc_id = doc.id

        self._embed_and_save(kb_id, chunks)
        self.repo.save_chunk_batch(chunks)
        self.repo.update_doc_status(doc.id, "ready", None)

        # Update doc stats
        doc.chunk_count = len(chunks)
        doc.total_tokens = sum(c.token_count or 0 for c in chunks)
        doc.updated_at = datetime.now(UTC).isoformat()
        self.repo.update_doc(doc)

        return len(chunks)

    def save_source(self, kb_id: str, doc_id: str | None = None, source_type: str | None = None):
        self.repo.save_source(kb_id, source_type)

    def _embed_and_save(self, kb_id: str, chunks: list[KbChunkEntity]):
        if not chunks:
            return
        try:
            kb = self.repo.find_kb_by_id(kb_id)
            embedding_model = kb.embedding_model if kb and kb.embedding_model else "text-embedding-3-small"
            chunk_contents = [c.content for c in chunks]
            embeddings = self.embedder.embed_batch(chunk_contents, embedding_model)
            for i, chunk in enumerate(chunks):
                if i < len(embeddings) and embeddings[i]:
                    chunk.embedding = serialize_embedding(embeddings[i])
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            logger.warning("Embedding batch failed: %s", type(exc).__name__)


def _guess_file_type(filename: str) -> str:
    ext = _get_extension(filename)
    if ext in ("md", "markdown"):
        return "md"
    return ext or "txt"


# ============================================================
# Import Strategies (aligned with Java ImportStrategy interface)
# ============================================================

class ImportStrategy:
    """Base interface for import strategies."""
    def get_source_type(self) -> str:
        raise NotImplementedError

    def import_source(self, kb_id: str, source_id: str,
                      context: ImportContext, params: ImportParams) -> int:
        raise NotImplementedError


class GitImportStrategy(ImportStrategy):
    def get_source_type(self) -> str:
        return "git"

    def import_source(self, kb_id, source_id, context, params):
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix="waliapi-git-")
            clone_url = ImportGuard.remote_url(params.repo_url)
            branch = ImportGuard.branch(params.branch)
            cmd = ["git", "clone", "--depth", "1", "--branch", branch, clone_url, temp_dir]
            env = os.environ.copy()
            if params.token:
                env.update({
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraheader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {params.token}",
                })
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120, env=env)
            if result.returncode != 0:
                logger.error(f"Git clone failed: {result.stderr}")
                return 0

            total_chunks = file_walk(temp_dir, params.excluded_dirs,
                                     params.included_files, params.max_file_size,
                                     lambda filename, relative_path, content:
                                     context.import_content(kb_id, filename, "git", relative_path, content))

            context.save_source(kb_id, None, "git")
            logger.info(f"Git import done: {params.repo_url} -> {total_chunks} chunks")
            return total_chunks
        except ApplicationError:
            raise
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.error(f"Git import failed: {params.repo_url}: {e}")
            return 0
        finally:
            if temp_dir:
                delete_directory(temp_dir)


class UrlImportStrategy(ImportStrategy):
    def get_source_type(self) -> str:
        return "url"

    def import_source(self, kb_id, source_id, context, params):
        url = ImportGuard.remote_url(params.url)
        try:
            with httpx.Client(follow_redirects=False, timeout=30) as client:
                current = url
                for _ in range(MAX_REDIRECTS + 1):
                    ImportGuard.remote_url(current)
                    with client.stream("GET", current, headers={"User-Agent": "WaLiAPI/1.0"}) as resp:
                        if 300 <= resp.status_code < 400:
                            location = resp.headers.get("location")
                            if not location:
                                raise ApplicationError("Import redirect has no destination", 422, "invalid_import_url")
                            current = urljoin(current, location)
                            continue
                        if resp.status_code != 200:
                            logger.error("URL fetch failed: %s -> HTTP %s", current, resp.status_code)
                            return 0
                        data = bytearray()
                        for chunk in resp.iter_bytes():
                            data.extend(chunk)
                            if len(data) > MAX_URL_BYTES:
                                raise ApplicationError("URL import exceeds size limit", 413, "import_limit")
                        content = bytes(data).decode("utf-8", errors="replace")
                        filename = self._extract_filename(current)
                        chunk_count = context.import_content(kb_id, filename, "url", current, content)
                        context.save_source(kb_id, None, "url")
                        logger.info("URL import done: %s -> %s chunks", current, chunk_count)
                        return chunk_count
                raise ApplicationError("Too many redirects", 422, "invalid_import_url")
        except ApplicationError:
            raise
        except (httpx.HTTPError, OSError) as e:
            logger.error("URL fetch failed: %s: %s", url, type(e).__name__)
            return 0

    @staticmethod
    def _extract_filename(url: str) -> str:
        path = urlparse(url).path
        name = path.rsplit("/", 1)[-1]
        return name if name else "imported_url"


class LocalDirImportStrategy(ImportStrategy):
    def get_source_type(self) -> str:
        return "local_dir"

    def import_source(self, kb_id, source_id, context, params):
        total_chunks = file_walk(params.dir_path, params.excluded_dirs,
                                 params.included_files, params.max_file_size,
                                 lambda filename, relative_path, content:
                                 context.import_content(kb_id, filename, "local_dir", relative_path, content))
        context.save_source(kb_id, None, "local_dir")
        logger.info(f"Local dir import done: {params.dir_path} -> {total_chunks} chunks")
        return total_chunks


# ============================================================
# ImporterService (aligned with Java ImporterService)
# ============================================================

class ImporterService:
    """Service to dispatch import by source type."""

    def __init__(self, kb_repository, text_splitter, embedder_service):
        self.repo = kb_repository
        self.context = ImportContext(kb_repository, text_splitter, embedder_service)
        self.strategies: dict[str, ImportStrategy] = {}
        self._register_defaults()

    def _register_defaults(self):
        for strategy in [GitImportStrategy(), UrlImportStrategy(), LocalDirImportStrategy()]:
            self.strategies[strategy.get_source_type()] = strategy

    def import_source(self, kb_id: str, body: dict) -> dict[str, Any]:
        source_type = body.get("sourceType") or body.get("source_type")
        if not source_type:
            return {"success": False, "message": "sourceType is required"}

        strategy = self.strategies.get(source_type)
        if not strategy:
            return {"success": False, "message": f"Unsupported source type: {source_type}"}

        params = ImportParams.from_dict(body)
        import uuid
        source_id = str(uuid.uuid4())
        total_chunks = strategy.import_source(kb_id, source_id, self.context, params)
        return {
            "success": True,
            "sourceId": source_id,
            "sourceType": source_type,
            "totalChunks": total_chunks,
        }
