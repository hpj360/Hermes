# M4 记忆层部署与中文验证笔记（P0-4）

> 状态：待实测（本机无 Ollama / 未安装 mem0，以下为验证步骤与预期，非实测结论）

## 1. Windows 本地部署验证清单

| 项 | 命令 / 步骤 | 预期 |
|---|---|---|
| 主依赖零新增 | `pip install -e .` 后 `python -c "import hermes"` | 不装 mem0 也能 import 与跑全测试 |
| optional extra | `pip install -e ".[mem0]"` | 安装 `mem0ai` 与传递依赖 |
| 后端降级 | `HERMES_MEMORY_BACKEND=mem0` 但未装 mem0 时 `hermes workbench memory audit` | `backend_healthy=false`，检索退回 RRF |
| 重建命令 | `hermes workbench memory rebuild` | 输出 `rebuilt backend index from N episodes` |

## 2. 中文 embedding / 抽取验证

默认 embedding 走 Ollama（`OLLAMA_EMBED_URL` / `OLLAMA_EMBED_MODEL`），中文建议
用 `bge-m3` 或 `gte-Qwen2`（需先 `ollama pull bge-m3`）。

**中文实体链接（F3 量化点）**：Mem0 默认 spaCy `en_core_web_sm` 只覆盖英文；
中文语料下实体链接收益接近零。验证项：

1. `pip install mem0ai[nlp]` + 中文模型，观察 `add` 后实体是否被正确抽取；
2. 若实体链接不可用/无效，将 Mem0 降级为「仅 LLM 事实抽取」，实体信号不参与
   RRF 第 5 路融合（在 `Mem0Backend.search` 中忽略无 metadata.episode_id 的结果
   即为兜底）。

## 3. 基准复现（Go/No-Go 判据）

```powershell
python scripts/benchmark/memory_bench.py --backend local_rrf   # 基线
python scripts/benchmark/memory_bench.py --backend mem0        # 候选
```

判据（ADR-0021）：recall@5 相对提升 ≥15%、p95 检索延迟 <500ms、每条 episode
增量 token <3K、Windows 本地部署通过。任一不达标 → 回退 MemOS adapter。

## 4. 已知环境现象（本机实测）

- 本地无 Ollama 时，RRF 的语义信号（Signal 4）每次查询会等待 embed 超时，
  p50 延迟 ~4s（连接层开销）。这是预期降级路径，不影响正确性；接 Ollama 后
  延迟恢复正常。若想测纯本地信号延迟，可临时把 `search_episodes_semantic` 的
  调用条件关闭或降低 `EmbeddingClient.timeout`。
- CJK bigram 分词补丁已落地（`_tokenize`），无空格中文语料召回从 0 提升到
  recall@5=0.9（`memory_queries.json` 种子语料实测）。
