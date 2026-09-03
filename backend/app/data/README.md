# 本地知识资料

SmartCoach 会从本目录读取健康、饮食与运动资料，并将正文及 FTS5 关键词索引写入 SQLite，将向量索引写入 ChromaDB。

公开仓库不分发缺少明确来源或再授权信息的原始资料。请仅放入你有权使用、处理和再分发的数据，并记录来源、版本、许可证与更新时间。

当前导入器识别以下文件名：

| 文件名 | 类别 | 建议内容 |
| --- | --- | --- |
| `calorie-of-food.csv` | `food` | 食物名称与每 100 克热量 |
| `recipe.csv` | `recipe` | 食谱、食物选择和适用条件 |
| `chinese-2011-compendium-of-physical-activities-v1.1.csv` | `exercise` | 活动名称、编码和 MET 值 |
| `optimize-the-dietary-structure.txt` | `health` | 饮食结构资料 |
| `scientific-literature-on-weight-loss.txt` | `health` | 带出处的减脂研究摘要 |

准备完成后，在 `backend/` 目录运行：

```powershell
uv run python scripts\rebuild_knowledge.py
```

没有配置 Embedding 服务时可构建纯关键词索引：

```powershell
uv run python scripts\rebuild_knowledge.py --no-embeddings
```

运行生成的 SQLite、WAL 文件和 `chroma_db_storage/` 都属于本地状态，不应提交到 Git。
