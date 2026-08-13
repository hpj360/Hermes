# ADR 0005: LLM 层引入 stream / retry / token counter

Status: Accepted
Date: 2026-08-13

## Context

`workbench/llm.py` 原本仅提供同步 `chat()` / `chat_json()`，能力缺口：

1. **无流式**：`urllib.urlopen(...).read()` 全量读取，无法流式消费长回答；
2. **无重试**：429/5xx 直接抛错，`scheduler.RetryPolicy` 的指数退避无法复用；
3. **无 token 计数**：P1 Token 熔断依赖 `orchestrator.AgentTask.token_limit`，
   但无精确计数实现，熔断语义名不副实。

## Decision

在 `workbench/llm.py` 内实现三项能力，保持 stdlib 零外部运行时依赖：

- `stream()`：`stream: true` + SSE 解析（`data: {json}`），逐 delta 产出
  `LlmStreamChunk`。
- 重试：新增 `LlmRetryPolicy`（本地 dataclass，避免依赖 `scheduler.RetryPolicy`
  造成跨模块耦合），`chat()`/`stream()` 对 429/5xx/URLError 自动指数退避，
  `max_retries=0` 时行为与旧版一致（默认不破坏现有调用方）。`make_llm_client`
  默认 `max_retries=2`。
- `count_tokens()`：优先 `tiktoken`（cl100k_base），缺失时降级为
  `ceil(len/4)` 启发式，确定性且不抛异常。

## Consequences

- **正面**：流式输出、自动重试、精确熔断；P1 Token 熔断从此可落地。
- **负面 / tradeoff**：`tiktoken` 是可选依赖（放 dev extras，未装时降级估算）；
  SSE 解析只覆盖 OpenAI 兼容格式，非兼容 provider 需适配。
- **后续约束**：新增 provider 若不走 OpenAI SSE 格式，需在 `_parse_sse_stream`
  或 provider 适配层扩展。
