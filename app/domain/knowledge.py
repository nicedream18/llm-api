"""Knowledge base domain services: text splitter, embedder, retriever, RAG."""
import re
import math
import json
import struct
import logging
import uuid
from typing import List, Optional

from app.domain.entities import (
    KbChunkEntity, SearchResultEntity, RagAnswerEntity, ProxyRequestEntity,
)

logger = logging.getLogger(__name__)


class ChunkConfig:
    def __init__(self, chunk_size=512, chunk_overlap=50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap


class TextSplitter:
    """Splits text into chunks with overlap, supports markdown heading-based splitting."""

    ASCII_CHARS_PER_TOKEN = 4.0
    NON_ASCII_CHARS_PER_TOKEN = 2.0

    def split(self, content, file_type, config, metadata=None):
        if not content or not content.strip():
            return []
        if config is None:
            config = ChunkConfig()
        if not file_type:
            file_type = ""
        lower = file_type.lower()
        if lower in ("md", "markdown"):
            return self._split_markdown(content, config, metadata)
        return self._split_text(content, config, metadata)

    def _split_text(self, content, config, metadata):
        chunks = []
        chunk_size = config.chunk_size
        overlap = config.chunk_overlap
        total_len = len(content)
        start = 0
        index = 0
        while start < total_len:
            end = min(start + chunk_size, total_len)
            if end < total_len:
                end = self._find_natural_boundary(content, start, end)
            chunk_content = content[start:end]
            token_count = self._estimate_tokens(chunk_content)
            meta = None
            if metadata:
                meta = json.dumps({"filePath": metadata.get("filePath", ""), "start": start, "end": end})
            chunks.append(KbChunkEntity(
                id=str(uuid.uuid4()), content=chunk_content, chunk_index=index,
                token_count=token_count, chunk_type="text",
                language=metadata.get("language") if metadata else None,
                metadata=meta,
            ))
            if end >= total_len:
                break
            start = max(end - overlap, start + 1)
            index += 1
        return chunks

    def _split_markdown(self, content, config, metadata):
        chunks = []
        lines = content.split("\n")
        current_section = []
        for line in lines:
            if line.startswith("#") and current_section:
                section_text = "\n".join(current_section)
                if len(section_text) > config.chunk_size:
                    chunks.extend(self._split_text(section_text, config, metadata))
                elif section_text.strip():
                    meta = None
                    if metadata:
                        meta = json.dumps({"filePath": metadata.get("filePath", ""), "heading": line.strip()})
                    chunks.append(KbChunkEntity(
                        id=str(uuid.uuid4()), content=section_text, chunk_index=len(chunks),
                        token_count=self._estimate_tokens(section_text), chunk_type="markdown",
                        metadata=meta,
                    ))
                current_section = [line]
            else:
                current_section.append(line)
        if current_section:
            section_text = "\n".join(current_section)
            if len(section_text) > config.chunk_size:
                chunks.extend(self._split_text(section_text, config, metadata))
            elif section_text.strip():
                meta = None
                if metadata:
                    meta = json.dumps({"filePath": metadata.get("filePath", "")})
                chunks.append(KbChunkEntity(
                    id=str(uuid.uuid4()), content=section_text, chunk_index=len(chunks),
                    token_count=self._estimate_tokens(section_text), chunk_type="markdown",
                    metadata=meta,
                ))
        return chunks

    def _find_natural_boundary(self, content, start, end):
        for i in range(end, start, -1):
            if i <= len(content) and content[i-1] in "\n.!? ":
                return i
        return end

    def _estimate_tokens(self, text):
        ascii_count = sum(1 for c in text if ord(c) < 128)
        non_ascii_count = len(text) - ascii_count
        return int(ascii_count / self.ASCII_CHARS_PER_TOKEN + non_ascii_count / self.NON_ASCII_CHARS_PER_TOKEN)



class EmbedderService:
    """Calls embedding API via channel dispatcher (OpenAI-compatible /embeddings)."""

    def __init__(self, dispatcher, channel_repository):
        self.dispatcher = dispatcher
        self.channel_repository = channel_repository
        import httpx
        self._client = httpx.Client(timeout=httpx.Timeout(connect=30, read=60, write=30, pool=10))

    def embed_batch(self, texts, model):
        if not texts:
            return []
        dispatch_result = self.dispatcher.dispatch(model)
        channel = dispatch_result.channel
        upstream_model = dispatch_result.upstream_model
        base = (channel.base_url or "").rstrip("/")
        url = f"{base}/embeddings"
        headers = {"Content-Type": "application/json"}
        if channel.type == "claude":
            headers["x-api-key"] = channel.api_key or ""
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {channel.api_key or ''}"
        body = {"model": upstream_model, "input": texts}
        resp = self._client.post(url, json=body, headers=headers)
        if resp.status_code < 200 or resp.status_code >= 300:
            raise Exception(f"Embedding API failed: HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        embeddings = [item["embedding"] for item in data.get("data", [])]
        if embeddings:
            dim = len(embeddings[0])
            for i, e in enumerate(embeddings):
                if len(e) != dim:
                    raise Exception(f"Embedding dimension mismatch at index {i}")
        return embeddings

    def embed(self, text, model):
        if not text or not text.strip():
            return []
        results = self.embed_batch([text], model)
        return results[0] if results else []


def serialize_embedding(vector):
    if not vector:
        return b""
    return struct.pack(f"<{len(vector)}f", *vector)


def deserialize_embedding(blob):
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RetrieverService:
    """Retrieves chunks via vector search, keyword (fulltext) search, and hybrid."""

    def __init__(self, kb_repository, embedder):
        self.kb_repository = kb_repository
        self.embedder = embedder

    def vector_search(self, kb_id, query_embedding, top_k):
        chunks = self.kb_repository.find_chunk_by_kb_id(kb_id)
        scored = []
        for chunk in chunks:
            if not chunk.embedding:
                continue
            emb = deserialize_embedding(chunk.embedding)
            score = cosine_similarity(query_embedding, emb)
            scored.append((chunk, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for chunk, score in scored[:top_k]:
            results.append(SearchResultEntity(
                chunk_id=chunk.id, doc_id=chunk.doc_id, content=chunk.content,
                score=score, metadata=self._parse_metadata(chunk.metadata),
            ))
        self._normalize_scores(results)
        return results

    def keyword_search(self, kb_id, query, top_k):
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []
        try:
            chunks = self.kb_repository.fulltext_search(kb_id, fts_query, top_k)
        except Exception as e:
            logger.warning(f"Fulltext search failed, falling back to LIKE: {e}")
            chunks = self._like_search(kb_id, query, top_k)
        results = []
        for chunk in chunks:
            results.append(SearchResultEntity(
                chunk_id=chunk.id, doc_id=chunk.doc_id, content=chunk.content,
                score=1.0, metadata=self._parse_metadata(chunk.metadata),
            ))
        return results

    def hybrid_search(self, kb_id, query, query_embedding, top_k, vector_weight=0.7, keyword_weight=0.3):
        vector_results = []
        if query_embedding:
            vector_results = self.vector_search(kb_id, query_embedding, top_k)
        keyword_results = self.keyword_search(kb_id, query, top_k)
        merged = {}
        for r in vector_results:
            merged[r.chunk_id] = SearchResultEntity(
                chunk_id=r.chunk_id, doc_id=r.doc_id, content=r.content,
                score=r.score * vector_weight, metadata=r.metadata,
            )
        for r in keyword_results:
            if r.chunk_id in merged:
                merged[r.chunk_id].score += r.score * keyword_weight
            else:
                merged[r.chunk_id] = SearchResultEntity(
                    chunk_id=r.chunk_id, doc_id=r.doc_id, content=r.content,
                    score=r.score * keyword_weight, metadata=r.metadata,
                )
        results = list(merged.values())
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def _like_search(self, kb_id, query, top_k):
        chunks = self.kb_repository.find_chunk_by_kb_id(kb_id)
        lower_q = query.lower()
        matched = [c for c in chunks if lower_q in (c.content or "").lower()]
        return matched[:top_k]

    def _build_fts_query(self, query):
        if not query or not query.strip():
            return ""
        sb = []
        i = 0
        while i < len(query):
            c = query[i]
            if self._is_cjk(c):
                if i + 1 < len(query) and self._is_cjk(query[i+1]):
                    if sb: sb.append(" ")
                    sb.append(f"+{c}{query[i+1]}*")
                    i += 2
                else:
                    if sb: sb.append(" ")
                    sb.append(f"+{c}*")
                    i += 1
            elif c.isalnum():
                start = i
                while i < len(query) and query[i].isalnum():
                    i += 1
                word = query[start:i]
                if sb: sb.append(" ")
                sb.append(f"+{word}*")
            else:
                i += 1
        return "".join(sb)

    def _is_cjk(self, c):
        cp = ord(c)
        return (0x4E00 <= cp <= 0x9FFF) or (0x3040 <= cp <= 0x30FF) or (0xAC00 <= cp <= 0xD7AF)

    def _parse_metadata(self, meta_str):
        if not meta_str:
            return {}
        try:
            return json.loads(meta_str)
        except Exception:
            return {}

    def _normalize_scores(self, results):
        if not results:
            return
        scores = [r.score for r in results]
        max_s, min_s = max(scores), min(scores)
        rng = max_s - min_s
        if rng > 0:
            for r in results:
                r.score = (r.score - min_s) / rng



class RagContextBuilder:
    """Builds context and prompts for RAG."""

    def build_context(self, results):
        if not results:
            return ""
        sb = []
        for i, r in enumerate(results):
            sb.append("=== \u6765\u6e90 " + str(i+1) + " ===\n")
            if r.metadata:
                file_path = r.metadata.get("filePath")
                heading = r.metadata.get("heading")
                if file_path:
                    sb.append("\u6587\u4ef6: " + str(file_path) + "\n")
                if heading:
                    sb.append("\u6807\u9898: " + str(heading) + "\n")
            sb.append("\u5185\u5bb9:\n" + (r.content or "") + "\n\n")
        return "".join(sb)

    def build_rag_prompt(self, context, query, history=None):
        sb = []
        sb.append("\u4f60\u662f\u4e00\u4e2a\u77e5\u8bc6\u5e93\u52a9\u624b\u3002\u8bf7\u6839\u636e\u4ee5\u4e0b\u68c0\u7d22\u5230\u7684\u4e0a\u4e0b\u6587\u56de\u7b54\u7528\u6237\u7684\u95ee\u9898\u3002\n\n")
        sb.append("\u6ce8\u610f\u4e8b\u9879:\n")
        sb.append("1. \u53ea\u6839\u636e\u63d0\u4f9b\u7684\u4e0a\u4e0b\u6587\u56de\u7b54\uff0c\u4e0d\u8981\u7f16\u9020\u4fe1\u606f\n")
        sb.append("2. \u5982\u679c\u4e0a\u4e0b\u6587\u4e0d\u8db3\u4ee5\u56de\u7b54\u95ee\u9898\uff0c\u8bf7\u8bf4\u660e\n")
        sb.append("3. \u5f15\u7528\u6765\u6e90\u65f6\u6807\u6ce8\u6765\u6e90\u7f16\u53f7\n\n")
        if history:
            sb.append("=== \u5bf9\u8bdd\u5386\u53f2 ===\n")
            for msg in history:
                sb.append(str(msg.get("role", "")) + ": " + str(msg.get("content", "")) + "\n")
            sb.append("\n")
        sb.append("=== \u68c0\u7d22\u4e0a\u4e0b\u6587 ===\n")
        sb.append(context)
        sb.append("\n")
        sb.append("=== \u7528\u6237\u95ee\u9898 ===\n")
        sb.append(query)
        return "".join(sb)

    def trim_context(self, prompt, context_limit):
        if not prompt:
            return ""
        max_prompt_tokens = context_limit - 1000
        if max_prompt_tokens <= 0:
            max_prompt_tokens = 2000
        estimated_tokens = len(prompt) // 4
        if estimated_tokens <= max_prompt_tokens:
            return prompt
        max_chars = max_prompt_tokens * 4
        if len(prompt) <= max_chars:
            return prompt
        head_len = max_chars // 3
        tail_len = max_chars - head_len
        return prompt[:head_len] + "\n\n[... \u4e0a\u4e0b\u6587\u5df2\u88c1\u526a ...]\n\n" + prompt[-tail_len:]

    def get_model_context_limit(self, model):
        if not model:
            return 4096
        lower = model.lower()
        if "gpt-4" in lower:
            if "128k" in lower: return 128000
            if "32k" in lower: return 32768
            return 8192
        if "gpt-3.5" in lower: return 16385
        if "claude-3" in lower: return 200000
        if "gemini" in lower: return 32768
        if "deepseek" in lower: return 64000
        if "qwen" in lower: return 32768
        if "glm" in lower: return 128000
        if "moonshot" in lower: return 128000
        return 4096


class RagService:
    """RAG service: embed query, retrieve, build context, call LLM."""

    def __init__(self, retriever_service, embedder_service, gateway_service, context_builder, search_strategy_factory=None):
        self.retriever_service = retriever_service
        self.embedder_service = embedder_service
        self.gateway_service = gateway_service
        self.context_builder = context_builder
        self.search_strategy_factory = search_strategy_factory

    def ask(self, kb_id, query, embedding_model, chat_model, top_k, history=None):
        query_embedding = self.embedder_service.embed(query, embedding_model)
        results = self.retriever_service.hybrid_search(kb_id, query, query_embedding, top_k, 0.7, 0.3)
        context = self.context_builder.build_context(results)
        prompt = self.context_builder.build_rag_prompt(context, query, history)
        prompt = self.context_builder.trim_context(prompt, self.context_builder.get_model_context_limit(chat_model))
        response = self._call_llm(chat_model, prompt, history)
        return self._build_answer(response, results)

    def ask_with_config(self, kb_id, query, embedding_model, chat_model, top_k, search_mode, vector_weight, keyword_weight, history=None):
        """Ask with config; uses search_by_mode which has fallback logic."""
        results = self.search_by_mode(kb_id, query, top_k, search_mode, embedding_model)
        context = self.context_builder.build_context(results)
        prompt = self.context_builder.build_rag_prompt(context, query, history)
        prompt = self.context_builder.trim_context(prompt, self.context_builder.get_model_context_limit(chat_model))
        response = self._call_llm(chat_model, prompt, history)
        return self._build_answer(response, results)

    def deep_research(self, kb_id, query, embedding_model, chat_model, top_k, max_rounds=3):
        all_results = []
        current_query = query
        all_answers = []
        for round_num in range(max_rounds):
            query_embedding = self.embedder_service.embed(current_query, embedding_model)
            results = self.retriever_service.hybrid_search(kb_id, current_query, query_embedding, top_k, 0.7, 0.3)
            all_results.extend(results)
            context = self.context_builder.build_context(results)
            prompt = self.context_builder.build_rag_prompt(context, current_query, None)
            prompt = self.context_builder.trim_context(prompt, self.context_builder.get_model_context_limit(chat_model))
            response = self._call_llm(chat_model, prompt, None)
            answer = self._extract_answer(response)
            all_answers.append(answer)
            follow_up = self._generate_follow_up(current_query, answer, chat_model)
            if not follow_up:
                break
            current_query = follow_up
        seen = {}
        for r in all_results:
            if r.chunk_id not in seen:
                seen[r.chunk_id] = r
        final_results = list(seen.values())[:top_k]
        combined = "\n\n".join(all_answers)
        return RagAnswerEntity(answer=combined, sources=self._build_sources(final_results), retrieval_details=self._build_details(final_results))

    def search_by_mode(self, kb_id, query, top_k, search_mode, embedding_model):
        """Search by mode with fallback (aligned with Java SearchStrategyFactory.searchWithFallback)."""
        mode = (search_mode or "keyword").lower()
        if mode == "keyword":
            return self.retriever_service.keyword_search(kb_id, query, top_k)
        query_embedding = None
        try:
            query_embedding = self.embedder_service.embed(query, embedding_model)
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to keyword search: {e}")
            return self.retriever_service.keyword_search(kb_id, query, top_k)
        if mode == "vector":
            try:
                results = self.retriever_service.vector_search(kb_id, query_embedding, top_k)
                if results:
                    return results
                logger.info("Vector search returned no results, falling back to keyword search")
                return self.retriever_service.keyword_search(kb_id, query, top_k)
            except Exception as e:
                logger.warning(f"Vector search failed, falling back to keyword: {e}")
                return self.retriever_service.keyword_search(kb_id, query, top_k)
        # hybrid
        try:
            results = self.retriever_service.hybrid_search(kb_id, query, query_embedding, top_k, 0.7, 0.3)
            if results:
                return results
            logger.info("Hybrid search returned no results, falling back to keyword search")
            return self.retriever_service.keyword_search(kb_id, query, top_k)
        except Exception as e:
            logger.warning(f"Hybrid search failed, falling back to keyword: {e}")
            return self.retriever_service.keyword_search(kb_id, query, top_k)

    def _call_llm(self, chat_model, prompt, history):
        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": prompt})
        body = {"model": chat_model, "messages": messages, "stream": False}
        request = ProxyRequestEntity(model=chat_model, body=body, stream=False, protocol_type="openai")
        return self.gateway_service.forward(request)

    def _build_answer(self, response, results):
        answer = ""
        usage = {}
        if response.success and response.body:
            answer = self._extract_answer(response)
            usage = {"prompt_tokens": response.prompt_tokens, "completion_tokens": response.completion_tokens, "total_tokens": response.total_tokens}
        else:
            answer = "\u62b1\u6b49\uff0c\u56de\u7b54\u751f\u6210\u5931\u8d25: " + (response.error_message or "\u672a\u77e5\u9519\u8bef")
        return RagAnswerEntity(answer=answer, sources=self._build_sources(results), usage=usage, retrieval_details=self._build_details(results))

    def _extract_answer(self, response):
        try:
            j = json.loads(response.body)
            choices = j.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", response.body)
            return response.body
        except Exception:
            return response.body

    def _build_sources(self, results):
        sources = []
        for r in (results or []):
            snippet = r.content or ""
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."
            filename = r.metadata.get("filePath", r.doc_id) if r.metadata else r.doc_id
            sources.append({"filename": filename, "score": r.score, "snippet": snippet})
        return sources

    def _build_details(self, results):
        details = []
        for r in (results or []):
            snippet = r.content or ""
            if len(snippet) > 150:
                snippet = snippet[:150] + "..."
            filename = r.metadata.get("filePath", r.doc_id) if r.metadata else r.doc_id
            details.append({"chunkId": r.chunk_id, "filename": filename, "score": r.score, "vectorScore": r.score, "snippet": snippet})
        return details

    def _generate_follow_up(self, original_query, previous_answer, chat_model):
        try:
            truncated = previous_answer[:500] if len(previous_answer) > 500 else previous_answer
            prompt = "\u57fa\u4e8e\u539f\u59cb\u95ee\u9898\u548c\u5df2\u6709\u56de\u7b54\uff0c\u751f\u6210\u4e00\u4e2a\u540e\u7eed\u95ee\u9898\u6765\u6df1\u5165\u7814\u7a76\u3002\n\u539f\u59cb\u95ee\u9898: " + original_query + "\n\u5df2\u6709\u56de\u7b54: " + truncated + "\n\u540e\u7eed\u95ee\u9898\uff08\u53ea\u8f93\u51fa\u95ee\u9898\u672c\u8eab\uff09:"
            response = self._call_llm(chat_model, prompt, None)
            if response.success and response.body:
                follow_up = self._extract_answer(response)
                return follow_up.strip() if follow_up else None
        except Exception as e:
            logger.warning(f"Generate follow-up failed: {e}")
        return None
