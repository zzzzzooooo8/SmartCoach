# AI 减脂教练后端

后端使用 FastAPI、LangGraph、SQLite 和 ChromaDB。SQLite 负责用户档案、减脂计划、饮食运动记录、长期与短期记忆、对话摘要及知识片段关键词索引；ChromaDB 专门保存 RAG 向量索引。

## 启动

```powershell
uv sync
uv run python scripts\rebuild_knowledge.py
uv run python main.py
```

服务默认运行在 `http://127.0.0.1:8000`，健康检查地址为 `/api/health`。

## 测试

```powershell
uv run python -m unittest discover -s tests -v
uv run python scripts\smoke_agent.py
```

## 数据

- SQLite 默认保存在 `app/data/fitness_agent.db`，可通过环境变量修改路径，其中不保存向量。
- ChromaDB 默认保存在 `app/data/chroma_db_storage`，正式 Collection 为 `fitness_knowledge_v2`。
- 资料重建脚本会读取 `app/data` 中约定名称的本地资料，按类型重新分块；正文与 FTS5 关键词索引写入 SQLite，Qwen3 向量写入 ChromaDB。
- 如果暂时没有嵌入模型密钥，可以使用 `--no-embeddings` 完成关键词资料库构建。
- SQLite 数据库、ChromaDB 持久化目录和环境变量文件已加入忽略规则，不应提交真实用户数据、向量文件或密钥。
- 公开仓库不包含来源或再授权信息不完整的原始健康资料，文件约定见 `app/data/README.md`。

环境变量参考 `.env.example`。
