import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import database
from app.vector_store import ChromaVectorStore


def backup_database(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(database.path)
    backup_connection = sqlite3.connect(target)
    try:
        source_connection.backup(backup_connection)
    finally:
        backup_connection.close()
        source_connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="将 SQLite 中的历史向量迁移至 ChromaDB")
    parser.add_argument(
        "--keep-sqlite-vectors",
        action="store_true",
        help="验证迁移但暂不删除 SQLite 的历史向量字段",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        default=database.path.with_name("fitness_agent.pre_chroma_migration.db"),
        help="移除历史向量字段前创建的 SQLite 备份路径",
    )
    args = parser.parse_args()

    rows = database.list_legacy_vector_chunks()
    vector_store = ChromaVectorStore()
    if not rows:
        print(
            f"SQLite 中没有待迁移向量；Chroma Collection "
            f"{vector_store.collection_name} 当前有 {vector_store.count()} 条。"
        )
        return

    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "content": row["content"],
                "embedding": json.loads(row["embedding"]),
                "metadata": {
                    "document_id": row["document_id"],
                    "document_name": row["document_name"],
                    "source": row["document_source"],
                    "version": row["document_version"],
                    "category": row["category"],
                    "chunk_index": row["chunk_index"],
                    "embedding_model": row.get("embedding_model")
                    or "Qwen/Qwen3-Embedding-0.6B",
                    "tags": json.loads(row["tags"]),
                    "suitable_for": json.loads(row["suitable_for"]),
                    "restrictions": json.loads(row["restrictions"]),
                },
            }
        )

    written = vector_store.upsert(items)
    verified = vector_store.contains_ids([item["id"] for item in items])
    if verified != len(items):
        raise RuntimeError(
            f"Chroma 迁移校验失败：期望 {len(items)} 条，实际找到 {verified} 条"
        )

    if not args.keep_sqlite_vectors:
        backup_database(args.backup)
        database.drop_legacy_embedding_columns()
        database.vacuum()

    print(
        f"迁移完成：写入 {written} 条，校验 {verified} 条，"
        f"Collection={vector_store.collection_name}，总量={vector_store.count()}。"
    )
    if not args.keep_sqlite_vectors:
        print(f"SQLite 历史向量字段已移除；迁移前备份：{args.backup}")


if __name__ == "__main__":
    main()
