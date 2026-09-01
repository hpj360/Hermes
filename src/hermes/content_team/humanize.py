"""de-AI 清理引擎（吸收 Humanizer 精髓，形态升级为 content_team 管线步骤）。

职责：在内容发布前清除 AI 生成文本的典型"AI 味"症状，让产出更接近人写。

规则集（中英文混合场景）：
1. 伪 em dash：`` -- `` → 中文逗号（AI 生成中文最常见的 M dash 症状）
2. 客套句移除："如需进一步帮助…"、"希望这对你有帮助" 等（句级）
3. 空洞结尾段移除："以上就是…" 开头的整段（段级）
4. 交互残留移除："当然，" / "好的，" 开头（对话前缀漏进正文）

证据链约束（与项目"不过滤"原则一致）：
de-AI 是**面向发布内容的显式管线步骤**，不是隐式后处理——每处变更
都记录在 ``changes`` 中（规则名 + 变更计数），清理本身可审计、可回滚
（版本快照天然保留清理前文本）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import cast

__all__ = ["DeaiResult", "deai_text"]

# 句级客套话（匹配即删整句，含尾部标点）
_PLEASANTRY_RE = re.compile(
    r"[^。！？\n]*?"
    r"(如需进一步帮助|希望这对你有帮助|希望对您有帮助|希望以上内容.*?有帮助"
    r"|如有任何问题.*?告诉我|欢迎随时提问)"
    r"[^。！？\n]*[。！？]?",
)

# 段级空洞结尾：以"以上就是"开头的整段（到空行或文末）
_HOLLOW_PARA_RE = re.compile(r"\n\s*以上就是[^\n]*(?:\n(?!\n)[^\n]*)*", re.M)

# 交互残留前缀
_CHAT_PREFIX_RE = re.compile(r"^\s*(当然|好的|明白了)[，,]\s*", re.M)

# 伪 em dash（M dash 症状）：空格-空格-空格-空格
_PSEUDO_DASH_RE = re.compile(r"\s+--\s+")


@dataclass
class DeaiResult:
    """de-AI 结果：清理后文本 + 可审计变更记录。"""

    text: str = ""
    changes: list[dict[str, object]] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        # changes 记录由 _apply 写入，count 恒为 int；object → int 需显式 cast
        return sum(int(cast(int, c["count"])) for c in self.changes)


def deai_text(text: str) -> DeaiResult:
    """对文本应用全部 de-AI 规则，返回清理结果与变更记录。"""
    changes: list[dict[str, object]] = []

    def _apply(pattern: re.Pattern[str], repl: str, rule: str, flags: int = 0) -> None:
        nonlocal text
        new_text, n = pattern.subn(repl, text)
        if n:
            changes.append({"rule": rule, "count": n})
            text = new_text

    _apply(_PSEUDO_DASH_RE, "，", "pseudo-dash→逗号")
    _apply(_PLEASANTRY_RE, "", "客套句移除")
    _apply(_HOLLOW_PARA_RE, "\n", "空洞结尾段移除")
    _apply(_CHAT_PREFIX_RE, "", "交互残留前缀移除")

    # 规整多余空行（清理后的副产品，不计入变更）
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return DeaiResult(text=text, changes=changes)
