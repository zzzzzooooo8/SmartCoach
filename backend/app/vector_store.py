import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv


load_dotenv()


@dataclass
class VectorHit:
    chunk_id: str
    content: str
    metadata: dict[str, Any]
    distance: float


def _batches(items: list[Any], size: int = 64) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


class ChromaVectorStore:
    def __init__(
        self,
        path: str | Path | None = None,
        collection_name: str | None = None,
    ) -> None:
        configured_path = path or os.getenv("CHROMA_PERSIST_DIRECTORY")
        default_path = Path(__file__).resolve().parent / "data" / "chroma_db_storage"
        self.path = Path(configured_path) if configured_path else default_path
        self.path.mkdir(parents=True, exist_ok=True)
        self.collection_name = (
            collection_name
            or os.getenv("CHROMA_COLLECTION_NAME")
            or "fitness_knowledge_v2"
        )
        self.client = chromadb.PersistentClient(
            path=str(self.path),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def available(self) -> bool:
        try:
            self.collection.count()
            return True
        except Exception:
            return False

    def count(self) -> int:
        return int(self.collection.count())

    def upsert(self, items: list[dict[str, Any]]) -> int:
        written = 0
        for batch in _batches(items):
            self.collection.upsert(
                ids=[str(item["id"]) for item in batch],
                documents=[str(item["content"]) for item in batch],
                embeddings=[item["embedding"] for item in batch],
                metadatas=[self._metadata(item.get("metadata", {})) for item in batch],
            )
            written += len(batch)
        return written

    def query(
        self,
        query_vector: list[float],
        category: str | None = None,
        limit: int = 30,
    ) -> list[VectorHit]:
        if not query_vector or self.count() == 0:
            return []
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": min(limit, self.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if category:
            kwargs["where"] = {"category": category}
        result = self.collection.query(**kwargs)
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            VectorHit(
                chunk_id=str(chunk_id),
                content=str(documents[index] or ""),
                metadata=self._decoded_metadata(metadatas[index] or {}),
                distance=float(distances[index]),
            )
            for index, chunk_id in enumerate(ids)
        ]

    def delete_by_source(self, source: str) -> None:
        self.collection.delete(where={"source": source})

    def ids_by_source(self, source: str) -> list[str]:
        result = self.collection.get(where={"source": source}, include=[])
        return [str(item) for item in (result.get("ids") or [])]

    def delete_ids(self, ids: list[str]) -> None:
        for batch in _batches(ids, size=500):
            self.collection.delete(ids=batch)

    def contains_ids(self, ids: list[str]) -> int:
        if not ids:
            return 0
        found = 0
        for batch in _batches(ids, size=500):
            result = self.collection.get(ids=batch, include=[])
            found += len(result.get("ids") or [])
        return found

    def close(self) -> None:
        system = getattr(self.client, "_system", None)
        if system is not None:
            system.stop()
        chromadb.api.client.SharedSystemClient.clear_system_cache()

    @staticmethod
    def _metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
        normalized: dict[str, str | int | float | bool] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                normalized[key] = value
            else:
                normalized[key] = json.dumps(value, ensure_ascii=False)
        return normalized

    @staticmethod
    def _decoded_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(metadata)
        for key in ("tags", "suitable_for", "restrictions"):
            value = decoded.get(key)
            if isinstance(value, str):
                try:
                    decoded[key] = json.loads(value)
                except ValueError:
                    pass
        return decoded
