#!/usr/bin/env python3
"""面向人的统一报告渲染器 + 输出契约（纯函数，零依赖）。

F2/F3：与 distill.py（内容层）配套的"表现层"。
- distill 负责 HTML 变干净；report 负责"干净内容怎么给人看"。
- 各 reader 输出格式统一为：报告头（标题 + 元信息行）→ 正文 → 提取统计脚注。
- emit() 统一 CLI 契约：``--json``（机器）/ 默认（人类报告）/ ``-o file``（保存）。

风格档位（吸收 Caveman 压缩哲学，架构裁决边界）：

- ``style="report"``（默认）——完整报告，面向人的存档/阅读。
- ``style="concise"``——极简档，面向人的交互回复（标题 + 元信息 + 首段截断）。
- **架构红线**：证据链路（checker 报告 / 轨迹 / 审计输出）**永不压缩**——
  本模块的 concise 档只允许用于面向人的交互回复；任何写入证据链
  （.learnings/、评估报告、审计日志）的调用方禁止传 ``style="concise"``。
  这与项目"不过滤"原则一致：机器证据逐字保留，压缩只发生在人机边界。

用法（作为库）：

    from report import render_report, emit

    report = render_report(
        title="文章标题",
        meta={"作者": "xxx", "发布时间": "2024-01-01", "来源": "微信公众号"},
        body=markdown,
        stats={"reduction_ratio": 0.81},
    )
    emit(payload={"title": ...}, report=report, fmt="report", output="out.md")

设计约束：
- 纯 Markdown 输出（保存 .md 后可直接阅读/渲染）
- meta 空值自动跳过（不输出"作者: "空行）
- 零第三方依赖（reader 无需 bs4 也能用本模块）
"""

from __future__ import annotations

import json
import sys
from typing import Any

__all__ = ["render_report", "emit", "STYLE_CONCISE_LIMIT"]

# concise 档正文截断长度（字符）：够看清主旨，不够全文阅读——
# 需要全文时用默认 report 档。
STYLE_CONCISE_LIMIT = 400


def render_report(
    title: str,
    meta: dict[str, str],
    body: str,
    stats: dict[str, Any] | None = None,
    *,
    style: str = "report",
) -> str:
    """渲染统一格式的人类可读报告。

    - title: 报告标题（空则省略标题行）
    - meta: 有序元信息（作者/发布时间/来源/URL 等）；空值键自动跳过
    - body: 正文（Markdown 或纯文本）
    - stats: 提取统计脚注（distill 的 stats dict；None 则省略脚注）
    - style: ``"report"``（完整，默认）或 ``"concise"``（交互回复用极简档）。
      证据链路（checker 报告/轨迹/审计）禁止使用 concise——见模块 docstring。
    """
    parts: list[str] = []

    if title:
        parts.append(f"# {title}\n")

    meta_lines = [f"{k}: {v}" for k, v in meta.items() if v]
    if meta_lines:
        parts.append("> " + " | ".join(meta_lines) + "\n")

    if style == "concise":
        # 极简档：正文截断 + 无统计脚注 + 提示如何取全文
        snippet = body.rstrip()[:STYLE_CONCISE_LIMIT]
        truncated = len(body) > STYLE_CONCISE_LIMIT
        parts.append(snippet + ("\n\n…（截断，完整内容用默认档）" if truncated else "\n"))
        return "\n".join(parts)

    if body:
        parts.append("---\n")
        parts.append(body.rstrip() + "\n")

    if stats:
        footnote = _format_stats(stats)
        if footnote:
            parts.append("---\n")
            parts.append(footnote + "\n")

    return "\n".join(parts)


def _format_stats(stats: dict[str, Any]) -> str:
    """stats dict → 单行脚注（缺字段自动降级，不硬编码字段）。"""
    bits: list[str] = []
    if "raw_chars" in stats and "distilled_chars" in stats:
        raw, distilled = stats["raw_chars"], stats["distilled_chars"]
        bits.append(f"原始 {raw:,} 字符 → 蒸馏 {distilled:,} 字符")
        ratio = stats.get("reduction_ratio")
        if ratio is not None:
            # 一位小数：避免 99.7% 四舍五入成"100%"造成误导
            bits.append(f"压缩 {ratio:.1%}")
    elif stats.get("mode"):
        bits.append(f"mode={stats['mode']}")
    if not bits:
        return ""
    return f"*提取统计*: " + " · ".join(bits)


def emit(
    payload: dict[str, Any],
    report: str,
    *,
    fmt: str = "report",
    output: str = "",
) -> int:
    """统一输出契约：fmt=json 输出 JSON，否则输出人类报告；output 非空则写文件。

    返回退出码（0 成功）。各 reader 的 main 末尾一律 ``sys.exit(emit(...))``。
    """
    if fmt == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = report

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入: {output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0
