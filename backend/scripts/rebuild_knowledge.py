import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import database
from app.rag import KnowledgeBase


def main() -> None:
    parser = argparse.ArgumentParser(description="重建 SQLite 关键词索引与 ChromaDB 向量库")
    parser.add_argument("--no-embeddings", action="store_true", help="只导入片段，暂不调用嵌入模型")
    args = parser.parse_args()
    data_dir = Path(__file__).resolve().parents[1] / "app" / "data"
    result = KnowledgeBase(database).rebuild(data_dir, with_embeddings=not args.no_embeddings)
    print(
        f"资料 {result['documents']} 份，片段 {result['chunks']} 个，"
        f"向量 {result['embeddings']} 个，模型 {result['embedding_model']}，"
        f"Chroma Collection {result['chroma_collection']} 共 {result['chroma_count']} 条"
    )


if __name__ == "__main__":
    main()
