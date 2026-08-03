"""Importer strategy system for knowledge base (aligned with Java importer/strategy package)."""
import os
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

import httpx

from app.domain.knowledge import ChunkConfig, serialize_embedding
from app.domain.entities import KbDocumentEntity, KbChunkEntity
from app.types.models import UploadDocDTO

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


def file_walk(root_path: str, excluded_dirs: List[str] = None,
              included_files: List[str] = None, max_file_size: int = 0,
              handler=None) -> int:
    """Walk a directory and call handler(filename, relative_path, content) for each file."""
    root = Path(root_path)
    if not root.is_dir():
        logger.error(f"Directory not found: {root_path}")
        return 0

    max_size = max_file_size if max_file_size and max_file_size > 0 else DEFAULT_MAX_FILE_SIZE
    exclude_set = set(excluded_dirs or []) | IGNORED_DIRS
    include_set = set(included_files) if included_files else None

    total_chunks = 0
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded dirs in-place (prunes traversal)
        dirnames[:] = [d for d in dirnames if d not in exclude_set]
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.getsize(filepath) > max_size:
                continue
            ext = _get_extension(filename)
            if include_set is not None:
                if ext not in include_set and filename not in include_set:
                    continue
            elif ext not in SUPPORTED_EXTS:
                continue
            files.append(filepath)

    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            relative_path = os.path.relpath(filepath, root)
            filename = os.path.basename(filepath)
            total_chunks += handler(filename, relative_path, content)
        except Exception as e:
            logger.warning(f"File processing failed: {filepath} -> {e}")

    logger.info(f"Directory walk done: {root_path} -> {len(files)} files, {total_chunks} chunks")
    return total_chunks


def delete_directory(path: str):
    """Recursively delete a directory."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _get_extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot + 1:].lower() if dot >= 0 else ""


# ============================================================
# ImportParams (aligned with Java ImportParams.java)
# ============================================================

class ImportParams:
    def __init__(self, repo_url: str = None, branch: str = None, token: str = None,
                 url: str = None, dir_path: str = None,
                 excluded_dirs: List[str] = None, included_files: List[str] = None,
                 max_file_size: int = None):
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
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

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
        doc.updated_at = datetime.now(timezone.utc).isoformat()
        self.repo.update_doc(doc)

        return len(chunks)

    def save_source(self, kb_id: str, doc_id: str = None, source_type: str = None):
        self.repo.save_source(kb_id, source_type)

    def _embed_and_save(self, kb_id: str, chunks: List[KbChunkEntity]):
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
        except Exception as e:
            logger.warning(f"Embedding batch failed: {e}")


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
            clone_url = params.repo_url
            if params.token:
                clone_url = params.repo_url.replace("https://", f"https://{params.token}@")

            branch = params.branch or "main"
            cmd = ["git", "clone", "--depth", "1", "--branch", branch, clone_url, temp_dir]
            result = subprocess.run(cmd, capture_output=True, text=True)
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
        except Exception as e:
            logger.error(f"Git import failed: {params.repo_url}: {e}")
            return 0
        finally:
            if temp_dir:
                delete_directory(temp_dir)


class UrlImportStrategy(ImportStrategy):
    def get_source_type(self) -> str:
        return "url"

    def import_source(self, kb_id, source_id, context, params):
        url = params.url
        try:
            with httpx.Client(follow_redirects=True, timeout=30) as client:
                resp = client.get(url, headers={"User-Agent": "WaLiAPI/1.0"})
                if resp.status_code != 200:
                    logger.error(f"URL fetch failed: {url} -> HTTP {resp.status_code}")
                    return 0
                content = resp.text
                filename = self._extract_filename(url)
                chunk_count = context.import_content(kb_id, filename, "url", url, content)
                context.save_source(kb_id, None, "url")
                logger.info(f"URL import done: {url} -> {chunk_count} chunks")
                return chunk_count
        except Exception as e:
            logger.error(f"URL fetch failed: {url}: {e}")
            return 0

    @staticmethod
    def _extract_filename(url: str) -> str:
        try:
            path = urlparse(url).path
            name = path.rsplit("/", 1)[-1]
            return name if name else "imported_url"
        except Exception:
            return "imported_url"


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
        self.strategies: Dict[str, ImportStrategy] = {}
        self._register_defaults()

    def _register_defaults(self):
        for strategy in [GitImportStrategy(), UrlImportStrategy(), LocalDirImportStrategy()]:
            self.strategies[strategy.get_source_type()] = strategy

    def import_source(self, kb_id: str, body: dict) -> Dict[str, Any]:
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
