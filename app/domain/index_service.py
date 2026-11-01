"""HNSW index service for knowledge base vector search."""
import heapq
import json
import logging
import math
import os
import re
import struct
import tempfile
import threading
from typing import Any, Optional, cast

logger = logging.getLogger(__name__)

# Default constants aligned with Java IndexService
INDEX_DIR = os.path.join(os.getcwd(), "data", "index")
DEFAULT_MAX_M = 16
DEFAULT_EF_CONSTRUCTION = 200
DEFAULT_EF_SEARCH = 50
INDEX_FORMAT_VERSION = 1
MAX_INDEX_FILE_BYTES = 512 * 1024 * 1024
_INDEX_IO_LOCK = threading.RLock()


class HnswIndex:
    """Pure-Python HNSW index (aligned with Java HnswIndex.java)."""

    def __init__(self, dim: int, max_m: int = DEFAULT_MAX_M,
                 ef_construction: int = DEFAULT_EF_CONSTRUCTION,
                 ef_search: int = DEFAULT_EF_SEARCH):
        if dim <= 0:
            raise ValueError("Index dimension must be positive")
        if max_m <= 0 or ef_construction <= 0 or ef_search <= 0:
            raise ValueError("HNSW parameters must be positive")
        self.format_version = INDEX_FORMAT_VERSION
        self.dim = dim
        self.max_m = max_m
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.nodes: list[dict[str, Any]] = []
        self.entry_point = -1
        self.initialized = False

    def build(self, ids: list[int], vectors: list[list[float]]):
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors length mismatch")
        self.nodes.clear()
        self.entry_point = -1
        self.initialized = False
        if not ids:
            return

        for i, idx in enumerate(ids):
            vector = vectors[i]
            if not self._valid_vector(vector, self.dim):
                raise ValueError(f"Invalid vector at index {i}")
            self.nodes.append({
                "id": idx,
                "vector": vector,
                "neighbours": [],
            })

        # For each node, find M nearest neighbours by cosine distance
        for i in range(len(self.nodes)):
            current = self.nodes[i]
            candidates = []
            for j in range(len(self.nodes)):
                if i == j:
                    continue
                dist = self._cosine_distance(current["vector"], self.nodes[j]["vector"])
                candidates.append((dist, j))

            candidates.sort(key=lambda x: x[0])
            current["neighbours"] = [c[1] for c in candidates[:self.max_m]]

        self.entry_point = 0
        self.initialized = True
        logger.info(f"HNSW index built: {len(self.nodes)} nodes, dim={self.dim}, maxM={self.max_m}")

    def search(self, query_vector: list[float], top_k: int) -> list[dict[str, Any]]:
        if top_k <= 0 or not self.initialized or not self.nodes:
            return []
        if not self._valid_vector(query_vector, self.dim):
            raise ValueError("Query vector dimension or values are invalid")

        visited = set()
        # Use a min-heap for candidates (distance, node_index)
        candidates: list[tuple[float, int]] = []
        # Use a max-heap for results (negate distance for max-heap behaviour in Python's min-heap)
        results: list[tuple[float, int]] = []

        entry_dist = self._cosine_distance(query_vector, self.nodes[self.entry_point]["vector"])
        heapq.heappush(candidates, (entry_dist, self.entry_point))
        visited.add(self.entry_point)

        ef = max(self.ef_search, top_k)

        while candidates:
            dist, idx = heapq.heappop(candidates)

            # If results full and current is farther than worst result, skip
            if len(results) >= ef and results and -results[0][0] < dist:
                continue

            heapq.heappush(results, (-dist, idx))
            if len(results) > ef:
                heapq.heappop(results)

            # Expand neighbours
            node = self.nodes[idx]
            for neighbour_idx in node["neighbours"]:
                if neighbour_idx not in visited:
                    visited.add(neighbour_idx)
                    n_dist = self._cosine_distance(query_vector, self.nodes[neighbour_idx]["vector"])
                    heapq.heappush(candidates, (n_dist, neighbour_idx))

        # Return top_k nearest
        sorted_results = sorted([(-neg_dist, idx) for neg_dist, idx in results])
        search_results = []
        for dist, idx in sorted_results[:top_k]:
            node = self.nodes[idx]
            search_results.append({
                "id": node["id"],
                "score": 1.0 - dist,
            })
        return search_results

    def save(self, path: str):
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = None
        with _INDEX_IO_LOCK:
            try:
                with tempfile.NamedTemporaryFile(prefix=".hnsw-", suffix=".tmp", dir=directory, delete=False) as f:
                    temporary = f.name
                    payload = {
                        "format": "waliapi-hnsw",
                        "format_version": self.format_version,
                        "dim": self.dim,
                        "max_m": self.max_m,
                        "ef_construction": self.ef_construction,
                        "ef_search": self.ef_search,
                        "entry_point": self.entry_point,
                        "initialized": self.initialized,
                        "nodes": self.nodes,
                    }
                    f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        logger.info(f"HNSW index saved: {path}")

    @staticmethod
    def load(path: str) -> Optional["HnswIndex"]:
        try:
            with _INDEX_IO_LOCK:
                if os.path.getsize(path) > MAX_INDEX_FILE_BYTES:
                    raise ValueError("HNSW index file exceeds the size limit")
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            if not isinstance(payload, dict) or payload.get("format") != "waliapi-hnsw":
                raise ValueError("Invalid HNSW index format")
            index = HnswIndex(
                payload["dim"], payload["max_m"],
                payload["ef_construction"], payload["ef_search"],
            )
            index.format_version = cast(int, payload.get("format_version"))
            index.entry_point = cast(int, payload.get("entry_point"))
            index.initialized = cast(bool, payload.get("initialized"))
            index.nodes = cast(list[dict[str, Any]], payload.get("nodes"))
            if not index._valid_index():
                raise ValueError("Invalid HNSW index format")
            logger.info(f"HNSW index loaded: {path}")
            return index
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError, AttributeError) as e:
            logger.error(f"HNSW index load failed: {path}: {e}")
            return None

    def _valid_index(self) -> bool:
        if type(getattr(self, "format_version", None)) is not int or self.format_version != INDEX_FORMAT_VERSION:
            return False
        if (type(self.dim) is not int or self.dim <= 0
                or type(self.entry_point) is not int or not self.initialized
                or not isinstance(self.nodes, list) or not self.nodes
                or self.entry_point < 0 or self.entry_point >= len(self.nodes)):
            return False
        ids = set()
        for node in self.nodes:
            if not isinstance(node, dict) or type(node.get("id")) is not int or node["id"] in ids:
                return False
            ids.add(node["id"])
            if not self._valid_vector(node.get("vector"), self.dim):
                return False
            neighbours = node.get("neighbours")
            if (not isinstance(neighbours, list)
                    or any(type(index) is not int or index < 0 or index >= len(self.nodes) for index in neighbours)):
                return False
        return True

    @staticmethod
    def _valid_vector(vector: Any, dim: int) -> bool:
        return bool(
            isinstance(vector, (list, tuple))
            and len(vector) == dim
            and all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in vector)
        )

    @staticmethod
    def _cosine_distance(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            raise ValueError(f"Vector dim mismatch: {len(a)} vs {len(b)}")
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a)
        norm_b = sum(y * y for y in b)
        denom = (norm_a ** 0.5) * (norm_b ** 0.5)
        if denom == 0:
            return 1.0
        return 1.0 - (dot / denom)


class IndexService:
    """Index service aligned with Java IndexService."""

    def __init__(self, kb_repository):
        self.repo = kb_repository
        os.makedirs(INDEX_DIR, exist_ok=True)
        logger.info(f"HNSW index directory: {INDEX_DIR}")

    @staticmethod
    def _safe_kb_id(kb_id: str) -> str:
        if not isinstance(kb_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", kb_id):
            raise ValueError("Invalid knowledge base id")
        return kb_id

    @staticmethod
    def validate_kb_id(kb_id: str) -> str:
        return IndexService._safe_kb_id(kb_id)

    def _index_path(self, kb_id: str) -> str:
        return os.path.join(INDEX_DIR, f"{self._safe_kb_id(kb_id)}.index")

    def build_index(self, kb_id: str) -> dict[str, Any]:
        logger.info(f"Building index: kbId={kb_id}")
        chunks = self.repo.find_chunk_by_kb_id(kb_id)
        if not chunks:
            return {"success": False, "message": "没有可索引的分块"}

        ids = []
        vectors = []
        skipped = 0

        dim = None
        for i, chunk in enumerate(chunks):
            vector = self._deserialize_vector(chunk.embedding)
            if vector and len(vector) > 0 and (dim is None or len(vector) == dim) and all(math.isfinite(float(value)) for value in vector):
                dim = dim or len(vector)
                ids.append(i)
                vectors.append(vector)
            else:
                skipped += 1

        if not ids:
            return {"success": False, "message": "没有有效的嵌入向量（需要先调用 Embedder 生成向量）"}

        dim = len(vectors[0])
        index = HnswIndex(dim, DEFAULT_MAX_M, DEFAULT_EF_CONSTRUCTION, DEFAULT_EF_SEARCH)
        index.build(ids, vectors)

        index_path = self._index_path(kb_id)
        index.save(index_path)

        # Update index metadata
        self.repo.upsert_index_meta(kb_id, "index_type", "hnsw")
        self.repo.upsert_index_meta(kb_id, "embedding_dim", str(dim))
        self.repo.upsert_index_meta(kb_id, "chunk_count", str(len(ids)))
        self.repo.upsert_index_meta(kb_id, "index_path", index_path)
        self.repo.upsert_index_meta(kb_id, "built_at", __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat())
        self.repo.upsert_index_meta(kb_id, "status", "ready")

        logger.info(f"Index built: kbId={kb_id}, total={len(chunks)}, indexed={len(ids)}, skipped={skipped}")
        return {
            "success": True,
            "totalChunks": len(chunks),
            "indexedChunks": len(ids),
            "embeddingDim": dim,
            "skipped": skipped,
            "indexPath": index_path,
        }

    def get_index_status(self, kb_id: str) -> dict[str, str]:
        self._safe_kb_id(kb_id)
        return self.repo.find_index_meta_by_kb_id(kb_id)

    def drop_index(self, kb_id: str) -> dict[str, Any]:
        file_deleted = self.remove_index_file(kb_id)
        self.repo.upsert_index_meta(kb_id, "status", "none")
        self.repo.upsert_index_meta(kb_id, "chunk_count", "0")
        self.repo.upsert_index_meta(kb_id, "built_at", "")

        logger.info(f"Index dropped: kbId={kb_id}, fileDeleted={file_deleted}")
        return {"success": True, "fileDeleted": file_deleted}

    def remove_index_file(self, kb_id: str) -> bool:
        index_path = self._index_path(kb_id)
        file_deleted = False
        if os.path.exists(index_path):
            os.remove(index_path)
            file_deleted = True
        return file_deleted

    def search_with_index(self, kb_id: str, query_vector: list[float], top_k: int):
        if top_k <= 0:
            return []
        index_path = self._index_path(kb_id)
        index = HnswIndex.load(index_path)
        if not index or not index.initialized:
            logger.warning(f"Index not found or not initialized: kbId={kb_id}")
            return []

        try:
            search_results = index.search(query_vector, top_k)
        except ValueError as exc:
            logger.warning("Index query rejected: kbId=%s error=%s", kb_id, exc)
            return []
        if not search_results:
            return []

        chunks = self.repo.find_chunk_by_kb_id(kb_id)
        chunk_map = {i: chunk for i, chunk in enumerate(chunks)}

        results = []
        for sr in search_results:
            chunk = chunk_map.get(sr["id"])
            if not chunk:
                continue
            results.append({
                "chunk_id": chunk.id,
                "doc_id": chunk.doc_id,
                "filename": self._extract_filename(chunk),
                "content": chunk.content,
                "score": sr["score"],
                "metadata": self._parse_metadata(chunk.metadata),
            })
        return results

    @staticmethod
    def _deserialize_vector(data: bytes) -> list[float] | None:
        if not data:
            return None
        if len(data) % 4:
            return None
        float_count = len(data) // 4
        return list(struct.unpack(f"<{float_count}f", data[:float_count * 4]))

    @staticmethod
    def _parse_metadata(metadata_str: str | None) -> dict[str, Any]:
        if not metadata_str:
            return {}
        import json
        try:
            return json.loads(metadata_str)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _extract_filename(chunk) -> str:
        if chunk.metadata:
            import json
            try:
                meta = json.loads(chunk.metadata)
                filename = meta.get("filename") or meta.get("filePath")
                if filename:
                    return filename
            except (TypeError, ValueError):
                logger.debug("Invalid chunk metadata for filename extraction", exc_info=True)
        return chunk.doc_id
