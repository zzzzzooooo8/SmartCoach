import csv
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

from app.database import Database, utc_now
from app.vector_store import ChromaVectorStore, VectorHit


load_dotenv()


DATA_FILES = {
    "calorie-of-food.csv": ("食物热量表", "food"),
    "recipe.csv": ("食谱与食物选择资料", "recipe"),
    "chinese-2011-compendium-of-physical-activities-v1.1.csv": ("运动活动代谢表", "exercise"),
    "optimize-the-dietary-structure.txt": ("饮食结构优化资料", "health"),
    "scientific-literature-on-weight-loss.txt": ("科学减脂文献", "health"),
}


@dataclass
class SearchResult:
    content: str
    source_name: str
    category: str
    score: float


class EmbeddingService:
    def __init__(self) -> None:
        self.model_name = os.getenv("EMBEDDING_MODEL_ENDPOINT", "Qwen/Qwen3-Embedding-0.6B")
        api_key = os.getenv("SILICON_API_KEY")
        base_url = os.getenv("SILICON_BASE_URL")
        self.client = None
        if api_key and base_url:
            self.client = OpenAIEmbeddings(
                model=self.model_name,
                api_key=api_key,
                base_url=base_url,
                chunk_size=64,
                check_embedding_ctx_length=False,
                max_retries=1,
                request_timeout=30,
            )

    @property
    def available(self) -> bool:
        return self.client is not None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.client:
            return []
        return self.client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float] | None:
        if not self.client:
            return None
        try:
            return self.client.embed_query(text)
        except Exception:
            return None


class RerankService:
    def __init__(self) -> None:
        self.model = os.getenv("RERANK_MODEL_ENDPOINT")
        self.base_url = os.getenv("RERANK_BASE_URL") or os.getenv("SILICON_BASE_URL")
        self.api_key = os.getenv("RERANK_API_KEY") or os.getenv("SILICON_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self.model and self.base_url and self.api_key)

    def rerank(self, query: str, candidates: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]] | None:
        if not self.available:
            return None
        url = f"{self.base_url.rstrip('/')}/rerank"
        body = json.dumps(
            {
                "model": self.model,
                "query": query,
                "documents": [item["content"] for item in candidates],
                "top_n": top_n,
                "return_documents": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            ranked = []
            for result in payload.get("results", []):
                index = int(result["index"])
                item = dict(candidates[index])
                item["score"] = float(result.get("relevance_score", item["score"]))
                ranked.append(item)
            return ranked or None
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            return None


def _tokens(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
    bigrams = {"".join(chinese[index:index + 2]) for index in range(max(0, len(chinese) - 1))}
    words = set(re.findall(r"[a-z0-9.]+", normalized))
    return bigrams | words


def _lexical_score(query: str, content: str) -> float:
    focused_query = query
    for generic in ("多少", "热量", "大卡", "千卡", "推荐", "什么", "怎么", "资料", "请问"):
        focused_query = focused_query.replace(generic, "")
    query_tokens = _tokens(focused_query) or _tokens(query)
    if not query_tokens:
        return 0
    content_tokens = _tokens(content)
    overlap = len(query_tokens & content_tokens)
    phrase_bonus = 0.4 if re.sub(r"\s+", "", query.lower()) in re.sub(r"\s+", "", content.lower()) else 0
    return overlap / max(1, len(query_tokens)) + phrase_bonus


def _chunk_text(text: str, maximum: int = 900, overlap: int = 120) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip()
        if current and len(candidate) > maximum:
            chunks.append(current)
            current = f"{current[-overlap:]}\n{line}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _read_chunks(path: Path, category: str) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    if category == "food":
        rows = []
        for row in csv.reader(text.splitlines()):
            values = [value.strip() for value in row if value.strip()]
            if values:
                rows.append("；".join(values))
        return rows
    if category == "exercise":
        lines = [line.strip().strip('"') for line in text.splitlines() if line.strip()]
        activities = []
        for index, line in enumerate(lines):
            if not re.match(r"^\d{5}\s+\d+(?:\.\d+)?\b", line):
                continue
            before = lines[index - 1] if index > 0 else ""
            after = lines[index + 1] if index + 1 < len(lines) else ""
            activities.append("\n".join(part for part in (before, line, after) if part))
        if activities:
            return activities
    return _chunk_text(text)


def detect_category(query: str) -> str | None:
    if any(token in query for token in ("疼", "痛", "受伤", "不舒服", "恢复", "禁忌")):
        return None
    if any(token in query for token in ("食谱", "菜谱", "吃什么", "怎么做", "晚餐", "午餐", "早餐")):
        return "recipe"
    if any(token in query for token in ("运动", "跑步", "快走", "骑车", "游泳", "消耗", "代谢当量", "MET")):
        return "exercise"
    if any(token in query for token in ("热量", "大卡", "千卡", "蛋白质", "碳水", "脂肪")):
        return "food"
    if any(token in query for token in ("减脂", "减肥", "健康", "饮食法", "平台期", "营养")):
        return "health"
    return None


class KnowledgeBase:
    def __init__(
        self,
        database: Database,
        embedding_service: EmbeddingService | None = None,
        rerank_service: RerankService | None = None,
        vector_store: ChromaVectorStore | None = None,
    ) -> None:
        self.database = database
        self.embedding_service = embedding_service or EmbeddingService()
        self.rerank_service = rerank_service or RerankService()
        self.vector_store = vector_store or ChromaVectorStore()

    def rebuild(self, data_dir: Path, with_embeddings: bool = True) -> dict[str, Any]:
        document_count = 0
        chunk_count = 0
        embeddings_created = 0
        for filename, (name, category) in DATA_FILES.items():
            path = data_dir / filename
            if not path.exists():
                continue
            raw = path.read_bytes()
            version = hashlib.sha256(raw).hexdigest()[:16]
            document = self.database.upsert_knowledge_document(name, category, str(path), version)
            contents = _read_chunks(path, category)
            vectors: list[list[float]] = []
            if with_embeddings and self.embedding_service.available and contents:
                try:
                    vectors = self.embedding_service.embed_documents(contents)
                except Exception:
                    vectors = []
            chunks: list[dict[str, Any]] = []
            vector_items: list[dict[str, Any]] = []
            for index, content in enumerate(contents):
                vector = vectors[index] if index < len(vectors) else None
                chunk_id = "chunk_" + hashlib.sha256(
                    f"{path}:{version}:{index}:{content}".encode("utf-8")
                ).hexdigest()
                if vector is not None:
                    embeddings_created += 1
                chunks.append(
                    {
                        "id": chunk_id,
                        "document_id": document["id"],
                        "content": content,
                        "chunk_index": index,
                        "category": category,
                        "tags": json.dumps([], ensure_ascii=False),
                        "suitable_for": json.dumps([], ensure_ascii=False),
                        "restrictions": json.dumps([], ensure_ascii=False),
                        "enabled": 1,
                        "updated_at": utc_now(),
                    }
                )
                if vector is not None:
                    vector_items.append(
                        {
                            "id": chunk_id,
                            "content": content,
                            "embedding": vector,
                            "metadata": {
                                "document_id": document["id"],
                                "document_name": name,
                                "source": str(path),
                                "version": version,
                                "category": category,
                                "chunk_index": index,
                                "embedding_model": self.embedding_service.model_name,
                                "tags": [],
                                "suitable_for": [],
                                "restrictions": [],
                            },
                        }
                    )
            old_vector_ids = set(self.vector_store.ids_by_source(str(path)))
            if vector_items:
                self.vector_store.upsert(vector_items)
                new_vector_ids = [item["id"] for item in vector_items]
                if self.vector_store.contains_ids(new_vector_ids) != len(new_vector_ids):
                    raise RuntimeError(f"Chroma 写入校验失败：{path.name}")
            self.database.replace_knowledge_chunks(document["id"], chunks)
            current_vector_ids = {item["id"] for item in vector_items}
            stale_ids = list(old_vector_ids - current_vector_ids)
            if stale_ids:
                self.vector_store.delete_ids(stale_ids)
            document_count += 1
            chunk_count += len(chunks)
        return {
            "documents": document_count,
            "chunks": chunk_count,
            "embeddings": embeddings_created,
            "embedding_model": self.embedding_service.model_name,
            "vector_store": "chroma",
            "chroma_collection": self.vector_store.collection_name,
            "chroma_count": self.vector_store.count(),
        }

    def search(self, query: str, category: str | None = None, limit: int = 4) -> list[SearchResult]:
        selected_category = category or detect_category(query)
        keyword_results, vector_results = self._retrieve(query, selected_category)
        if not keyword_results and not vector_results and selected_category:
            keyword_results, vector_results = self._retrieve(query, None)
        recalled = self._fuse(keyword_results, vector_results, limit=15)
        reranked = self.rerank_service.rerank(query, recalled, limit) if recalled else None
        final = (reranked or recalled)[:limit]
        return [
            SearchResult(
                content=item["content"],
                source_name=item["document_name"],
                category=item["category"],
                score=round(float(item["score"]), 4),
            )
            for item in final
        ]

    def _retrieve(
        self,
        query: str,
        category: str | None,
    ) -> tuple[list[dict[str, Any]], list[VectorHit]]:
        keyword_results = self.database.search_knowledge_keywords(
            query, category=category, limit=30
        )
        if not keyword_results:
            fallback = []
            for item in self.database.list_knowledge_chunks(category):
                score = _lexical_score(query, item["content"])
                if score > 0:
                    candidate = dict(item)
                    candidate["keyword_score"] = score
                    fallback.append(candidate)
            fallback.sort(key=lambda item: item["keyword_score"], reverse=True)
            keyword_results = fallback[:30]

        vector_results: list[VectorHit] = []
        if self.vector_store.available and self.vector_store.count() > 0:
            query_vector = self.embedding_service.embed_query(query)
            if query_vector:
                vector_results = self.vector_store.query(
                    query_vector, category=category, limit=30
                )
        return keyword_results, vector_results

    def _fuse(
        self,
        keyword_results: list[dict[str, Any]],
        vector_results: list[VectorHit],
        limit: int,
    ) -> list[dict[str, Any]]:
        fused: dict[str, dict[str, Any]] = {}
        for rank, item in enumerate(keyword_results, start=1):
            candidate = dict(item)
            candidate["score"] = candidate.get("score", 0.0) + 1 / (60 + rank)
            fused[item["id"]] = candidate

        vector_ids = [item.chunk_id for item in vector_results]
        database_rows = {
            item["id"]: item for item in self.database.get_knowledge_chunks(vector_ids)
        }
        for rank, hit in enumerate(vector_results, start=1):
            candidate = fused.get(hit.chunk_id)
            if candidate is None:
                row = database_rows.get(hit.chunk_id)
                if row is not None:
                    candidate = dict(row)
                else:
                    candidate = {
                        "id": hit.chunk_id,
                        "content": hit.content,
                        "document_name": hit.metadata.get("document_name", "未知资料"),
                        "category": hit.metadata.get("category", "unknown"),
                    }
                candidate["score"] = 0.0
                fused[hit.chunk_id] = candidate
            candidate["score"] = float(candidate.get("score", 0.0)) + 1 / (60 + rank)

        return sorted(
            fused.values(), key=lambda item: float(item["score"]), reverse=True
        )[:limit]

    def health(self) -> dict[str, Any]:
        return {
            "available": self.vector_store.available,
            "store": "chroma",
            "path": str(self.vector_store.path),
            "collection": self.vector_store.collection_name,
            "count": self.vector_store.count() if self.vector_store.available else 0,
            "embedding_available": self.embedding_service.available,
            "embedding_model": self.embedding_service.model_name,
            "rerank_available": self.rerank_service.available,
        }

    def format_results(self, results: list[SearchResult]) -> str:
        if not results:
            return "资料库没有找到足够相关的依据。"
        return "\n\n".join(
            f"资料 {index + 1}（来源：{item.source_name}）：\n{item.content}"
            for index, item in enumerate(results)
        )
