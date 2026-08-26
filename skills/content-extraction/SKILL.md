---
name: content-extraction
description: >
  Shared content distillation engine for web readers. Use when building or
  modifying a reader skill that converts fetched HTML into clean Markdown,
  when pages carry navigation/footer/cookie-banner noise that wastes tokens,
  or when you need unified web content extraction with reduction stats.
  Engine-only: no fetching (UA rotation / retries / captcha handling belong
  to caller readers).
---

# Content Extraction（共享蒸馏引擎）

把"URL → 纯净 Markdown"的清洗逻辑统一到一处（Defuddle 思想）：
各 reader 只保留平台特异的**获取策略**（UA 轮换、重试、验证码降级链），
**清洗/定位/转换/统计**全部复用本引擎。

## 职责边界

| 职责 | 归属 |
|---|---|
| 怎么拿到 HTML（UA/重试/验证码/降级链） | 各 reader（平台特异） |
| HTML → 干净 Markdown（剥离/定位/转换） | 本引擎（统一） |

## 使用

```python
import sys
from pathlib import Path

# 寻址共享引擎（skill-sync symlink/复制分发均可解析）
ENGINE = Path(__file__).resolve().parents[2] / "content-extraction" / "scripts"
sys.path.insert(0, str(ENGINE))
from distill import distill

result = distill(
    html, url,
    content_selectors=["#js_content"],          # 平台特异容器（可选）
    meta_selectors={"author": ["#js_name"]},    # 平台特异元数据（可选）
)
print(result.title, result.stats["reduction_ratio"])
```

CLI（管道）：

```bash
curl -sL https://example.com/a | python3 distill.py --url https://example.com/a
```

## 统一输出契约 `DistilledContent`

`url / title / author / publish_time / markdown / content_text / stats`

`stats` 含 `raw_chars / distilled_chars / reduction_ratio / container_found`，
供 token 成本归因（接入后可量化"蒸馏省了多少"）。

## 已接入 reader

- wechat-reader（微信公众号：UA 轮换 + 验证码检测 → 本引擎清洗）

## 测试

主项目 `tests/test_content_extraction.py`（golden 场景 + 压缩统计 + 降级路径）。
