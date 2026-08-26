---
name: content-extraction
description: >
  Shared content distillation engine for web readers. Use when building or
  modifying a reader skill that converts fetched HTML into clean Markdown,
  when pages carry navigation/footer/cookie-banner noise that wastes tokens,
  or when you need unified web content extraction with reduction stats.
  Also provides the unified human-facing report renderer and output contract
  (report.py): render_report + emit give every reader the same "--json /
  report / -o file" CLI surface. Engine-only: no fetching (UA rotation /
  retries / captcha handling belong to caller readers).
---

# Content Extraction（共享蒸馏引擎）

把"URL → 纯净 Markdown"的清洗逻辑统一到一处（Defuddle 思想）：
各 reader 只保留平台特异的**获取策略**（UA 轮换、重试、验证码降级链），
**清洗/定位/转换/统计**全部复用本引擎。

## 职责边界

| 职责 | 归属 |
|---|---|
| 怎么拿到 HTML（UA/重试/验证码/降级链） | 各 reader（平台特异） |
| HTML → 干净 Markdown（剥离/定位/转换） | 本引擎 distill.py（统一） |
| 面向人的报告格式 + CLI 输出契约 | 本引擎 report.py（统一） |

## 使用

```python
import sys
from pathlib import Path

# 寻址共享引擎（skill-sync symlink/复制分发均可解析）
ENGINE = Path(__file__).resolve().parents[2] / "content-extraction" / "scripts"
sys.path.insert(0, str(ENGINE))
from distill import distill
from report import emit, render_report

result = distill(
    html, url,
    content_selectors=["#js_content"],          # 平台特异容器（可选）
    meta_selectors={"author": ["#js_name"]},    # 平台特异元数据（可选）
)

# 面向人的统一报告 + 输出契约（--json / 报告 / -o 文件）
report = render_report(
    title=result.title,
    meta={"来源": "微信公众号", "作者": result.author},
    body=result.markdown,
    stats=result.stats,
)
sys.exit(emit(result.to_dict(), report, fmt="report", output="out.md"))
```

CLI（管道）：

```bash
curl -sL https://example.com/a | python3 distill.py --url https://example.com/a
```

## 统一输出契约 `DistilledContent`

`url / title / author / publish_time / markdown / content_text / stats`

`stats` 含 `raw_chars / distilled_chars / reduction_ratio / container_found`，
供 token 成本归因（接入后可量化"蒸馏省了多少"）。

## 统一报告契约（report.py）

`render_report(title, meta, body, stats)` → `# 标题` + `> 元信息行` + 正文 + `*提取统计*` 脚注；
`emit(payload, report, fmt, output)` → `--json`（机器）/ 报告（人）/ `-o file`（保存）三模式。

风格档位：`style="concise"`（面向人的交互回复，正文截断+无脚注）；
默认完整档。**证据链路（checker 报告/轨迹/审计）永不压缩**——
concise 只允许出现在人机边界。

reader 接入后自动获得一致的人类可读输出与 CLI 表面。

## 项目级输出规范（所有技能引用，含 prompt 型）

无论有无脚本，技能产出面向人的报告时遵循统一结构：

1. `# 标题`（一句话说明产出物）
2. `> 元信息行`（来源/作者/时间/范围，`k: v` 用 ` | ` 连接，空值省略）
3. `---` 分隔
4. 正文（Markdown）
5. `*统计脚注*`（可选：数据量/压缩比等归因信息）

CLI 表面（有脚本的技能）：`--json`（机器模式）/ 默认（人类报告）/ `-o file`（写文件）。
JSON-only 工具（如 figma-reader）至少提供 `-o` 写文件 + 结构化输出。

## 已接入 reader

- wechat-reader（微信公众号：UA 轮换 + 验证码检测 → 本引擎清洗 + 报告，含 `--concise`）
- douyin-reader（抖音：yt-dlp/whisper 获取 → 本引擎报告 + 输出契约）
- youtube-watcher（YouTube 字幕：yt-dlp 获取 → 本引擎报告 + 输出契约）
- brave-search（通用网页：content.py 主路径走本引擎；content.js 为 node-only 降级）
- stock-analysis（股票分析：自有文本格式保留，输出走 emit 统一契约 + `-o`）
- tavily-search（搜索：JS 侧对齐统一报告结构 + `--json`；figma-reader 已达标 `-o`+JSON）

## 测试

主项目 `tests/test_content_extraction.py`（golden 场景 + 压缩统计 + 降级路径
+ 报告渲染 + 输出契约 + reader 接入一致性）。
