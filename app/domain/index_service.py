"""HNSW index service for knowledge base vector search."""
import os
import struct
import logging
import heapq
from typing import List, Optional, Dict, Any
from collections import OrderedDict

logger = logging.getLogger(__name__)

# Default constants aligned with Java IndexService
INDEX_DIR = os.path.join(os.getcwd(), "data", "index")
DEFAULT_MAX_M = 16
DEFAULT_EF_CONSTRUCTION = 200
DEFAULT_EF_SEARCH = 50


class HnswIndex:
    """Pure-Python HNSW index (aligned with Java HnswIndex.java)."""

    def __init__(self, dim: int, max_m: int = DEFAULT_MAX_M,
                 ef_construction: int = DEFAULT_EF_CONSTRUCTION,
                 ef_search: int = DEFAULT_EF_SEARCH):
        self.dim = dim
        self.max_m = max_m
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.nodes: List[Dict[str, Any]] = []
        self.entry_point = -1
        self.initialized = False

    def build(self, ids: List[int], vectors: List[List[float]]):
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors length mismatch")
        if not ids:
            return

        self.nodes.clear()
        for i, idx in enumerate(ids):
            self.nodes.append({
                "id": idx,
                "vector": vectors[i],
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

    def search(self, query_vector: List[float], top_k: int) -> List[Dict[str, Any]]:
        if not self.initialized or not self.nodes:
            return []

        visited = set()
        # Use a min-heap for candidates (distance, node_index)
        candidates = []
        # Use a max-heap for results (negate distance for max-heap behaviour in Python's min-heap)
        results = []

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
        import pickle
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)
        logger.info(f"HNSW index saved: {path}")

    @staticmethod
    def load(path: str) -> Optional["HnswIndex"]:
        import pickle
        try:
            with open(path, "rb") as f:
                index = pickle.load(f)
            logger.info(f"HNSW index loaded: {path}")
            return index
        except Exception as e:
            logger.error(f"HNSW index load failed: {path}: {e}")
            return None

    @staticmethod
    def _cosine_distance(a: List[float], b: List[float]) -> float:
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

    def build_index(self, kb_id: str) -> Dict[str, Any]:
        logger.info(f"Building index: kbId={kb_id}")
        chunks = self.repo.find_chunk_by_kb_id(kb_id)
        if not chunks:
            return {"success": False, "message": "没有可索引的分块"}

        ids = []
        vectors = []
        skipped = 0

        for i, chunk in enumerate(chunks):
            vector = self._deserialize_vector(chunk.embedding)
            if vector and len(vector) > 0:
                ids.append(i)
                vectors.append(vector)
            else:
                skipped += 1

        if not ids:
            return {"success": False, "message": "没有有效的嵌入向量（需要先调用 Embedder 生成向量）"}

        dim = len(vectors[0])
        index = HnswIndex(dim, DEFAULT_MAX_M, DEFAULT_EF_CONSTRUCTION, DEFAULT_EF_SEARCH)
        index.build(ids, vectors)

        index_path = os.path.join(INDEX_DIR, f"{kb_id}.index")
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
            "skipped": skipped,
            "indexPath": index_path,
        }

    def get_index_status(self, kb_id: str) -> Dict[str, str]:
        return self.repo.find_index_meta_by_kb_id(kb_id)

    def drop_index(self, kb_id: str) -> Dict[str, Any]:
        index_path = os.path.join(INDEX_DIR, f"{kb_id}.index")
        file_deleted = False
        if os.path.exists(index_path):
            os.remove(index_path)
            file_deleted = True

        self.repo.upsert_index_meta(kb_id, "status", "none")
        self.repo.upsert_index_meta(kb_id, "chunk_count", "0")
        self.repo.upsert_index_meta(kb_id, "built_at", "")

        logger.info(f"Index dropped: kbId={kb_id}, fileDeleted={file_deleted}")
        return {"success": True, "fileDeleted": file_deleted}

    def search_with_index(self, kb_id: str, query_vector: List[float], top_k: int):
        index_path = os.path.join(INDEX_DIR, f"{kb_id}.index")
        index = HnswIndex.load(index_path)
        if not index or not index.initialized:
            logger.warning(f"Index not found or not initialized: kbId={kb_id}")
            return []

        search_results = index.search(query_vector, top_k)
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
    def _deserialize_vector(data: bytes) -> Optional[List[float]]:
        if not data:
            return None
        float_count = len(data) // 4
        return list(struct.unpack(f"<{float_count}f", data[:float_count * 4]))

    @staticmethod
    def _parse_metadata(metadata_str: Optional[str]) -> Dict[str, Any]:
        if not metadata_str:
            return {}
        import json
        try:
            return json.loads(metadata_str)
        except Exception:
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
            except Exception:
                pass
        return chunk.doc_id
