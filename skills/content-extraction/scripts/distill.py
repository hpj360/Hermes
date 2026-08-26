#!/usr/bin/env python3
"""content-extraction 共享蒸馏引擎（纯函数，无网络）。

职责边界（Defuddle 思想的统一落地）：
- Reader 技能负责"怎么拿到 HTML"——UA 轮换、重试、验证码检测、降级链
  （平台特异，不共享）。
- 本引擎负责"HTML 变干净"——噪声剥离、正文容器定位、元数据提取、
  HTML→Markdown 转换、压缩统计（通用，统一实现）。

输出统一契约 ``DistilledContent``，任何 reader 接入后自动获得全部清洗改进。

用法（作为库）：

    from distill import distill
    result = distill(html, url, content_selectors=["#js_content"])

用法（作为 CLI）：

    echo "<html>..." | python3 distill.py --url https://e.com/a
    python3 distill.py --file page.html --url https://e.com/a

依赖：beautifulsoup4（可选 lxml 加速）；缺失时降级为正则粗暴剥离。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    from bs4 import BeautifulSoup, NavigableString, Tag

    _HAS_BS4 = True
except ImportError:  # pragma: no cover - 环境缺依赖时的降级路径
    _HAS_BS4 = False

__all__ = [
    "DistilledContent",
    "NOISE_TAGS",
    "GENERIC_CONTENT_SELECTORS",
    "strip_noise",
    "locate_content",
    "extract_metadata",
    "html_to_markdown",
    "distill",
]

# 噪声元素：导航/页脚/Cookie 横幅/侧栏广告/脚本样式（Defuddle 剥离集）
NOISE_TAGS = [
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "iframe", "svg", "button", "select",
]

# 通用正文容器候选（按优先级；reader 可传入平台特异选择器置于最前）
GENERIC_CONTENT_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    ".content",
    "#content",
    "#js_content",          # 微信公众号
    ".rich_media_content",  # 微信公众号（旧）
    ".Post-RichTextContainer",  # 知乎
    ".topic-richtext",      # 知乎专栏
    "#article",             # 一般站点
]

# 通用元数据选择器（reader 可覆盖/前置平台特异选择器）。
# 顺序即优先级：结构化声明（og:/meta）先于页面元素（h1 可能是站点横幅）。
GENERIC_META_SELECTORS = {
    "title": ['meta[property="og:title"]', "title", "h1"],
    "author": [
        'meta[name="author"]',
        'meta[property="article:author"]',
        ".author",
        "#js_name",  # 微信公众号
    ],
    "publish_time": [
        'meta[property="article:published_time"]',
        "time",
        "#publish_time",  # 微信公众号
    ],
}


@dataclass
class DistilledContent:
    """统一输出契约：任何 reader 蒸馏后的网页正文。"""

    url: str = ""
    title: str = ""
    author: str = ""
    publish_time: str = ""
    markdown: str = ""
    content_text: str = ""
    # 证据统计：原始/蒸馏字符数与压缩比（供 token 成本归因）
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "publish_time": self.publish_time,
            "markdown": self.markdown,
            "content_text": self.content_text,
            "stats": self.stats,
        }


def strip_noise(soup: Any) -> None:
    """原地剥离噪声元素（导航/页脚/广告/脚本/样式）。"""
    if not _HAS_BS4:
        return
    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()


def locate_content(
    soup: Any,
    extra_selectors: list[str] | None = None,
) -> Any:
    """定位正文容器：extra_selectors 优先，然后通用候选。

    候选按顺序取第一个"有实际文本"的（避免命中空壳容器）。
    """
    if not _HAS_BS4:
        return None
    selectors: list[str] = []
    if extra_selectors:
        selectors.extend(extra_selectors)
    selectors.extend(GENERIC_CONTENT_SELECTORS)

    # id/class 直选（soup.select_one 对 [role='main'] 类也适用）
    for sel in selectors:
        try:
            el = soup.select_one(sel)
        except Exception:  # 非法选择器则跳过
            continue
        if el is not None and len(el.get_text(strip=True)) >= 40:
            return el
    return None


def _meta_text(el: Any) -> str:
    """元素/元标签的文本提取（meta 取 content 属性，其余取文本）。"""
    if el is None:
        return ""
    if el.name == "meta":
        return (el.get("content") or "").strip()
    return el.get_text(strip=True)


def extract_metadata(
    soup: Any,
    html: str,
    extra_selectors: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """提取 title/author/publish_time（平台选择器优先，通用兜底）。"""
    meta: dict[str, str] = {"title": "", "author": "", "publish_time": ""}
    if not _HAS_BS4:
        # 正则兜底：og:title / <title>
        m = re.search(r'property="og:title"\s+content="([^"]+)"', html)
        if not m:
            m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            meta["title"] = m.group(1).strip()
        return meta

    merged: dict[str, list[str]] = {}
    for key, generic in GENERIC_META_SELECTORS.items():
        extra = (extra_selectors or {}).get(key, [])
        merged[key] = list(extra) + generic

    for key, selectors in merged.items():
        for sel in selectors:
            try:
                el = soup.select_one(sel)
            except Exception:
                continue
            text = _meta_text(el)
            if text:
                meta[key] = text
                break

    # 标题正则兜底（微信 var msg_title 等内联变量）
    if not meta["title"]:
        m = re.search(r'var\s+msg_title\s*=\s*["\'](.+?)["\']', html)
        if m:
            meta["title"] = m.group(1).strip()
    return meta


def html_to_markdown(element: Any, depth: int = 0) -> str:
    """HTML 元素 → Markdown（源自 wechat-reader 的成熟递归实现）。

    增强：pre/code 围栏代码块（技术站点）。
    """
    if not _HAS_BS4:
        return ""
    if depth > 6:
        return element.get_text(strip=True) if element else ""

    md_parts: list[str] = []
    for child in element.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                md_parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue

        tag_name = (child.name or "").lower()
        text = child.get_text(strip=True)

        if tag_name in ("h1", "h2", "h3"):
            md_parts.append(f"\n\n## {text}\n\n")
        elif tag_name in ("h4", "h5", "h6"):
            md_parts.append(f"\n\n### {text}\n\n")
        elif tag_name == "p":
            inner = html_to_markdown(child, depth + 1)
            if inner.strip():
                md_parts.append(f"\n{inner.strip()}\n")
        elif tag_name == "br":
            md_parts.append("\n")
        elif tag_name in ("strong", "b"):
            if text:
                md_parts.append(f"**{text}**")
        elif tag_name in ("em", "i"):
            if text:
                md_parts.append(f"*{text}*")
        elif tag_name == "pre":
            code = child.get_text()
            md_parts.append(f"\n```\n{code.strip()}\n```\n")
        elif tag_name == "code":
            md_parts.append(f"`{text}`")
        elif tag_name in ("ul", "ol"):
            for i, li in enumerate(child.find_all("li", recursive=False), 1):
                li_text = li.get_text(strip=True)
                if not li_text:
                    continue
                bullet = f"{i}." if tag_name == "ol" else "-"
                md_parts.append(f"{bullet} {li_text}\n")
            md_parts.append("\n")
        elif tag_name == "blockquote":
            for line in text.split("\n"):
                if line.strip():
                    md_parts.append(f"> {line.strip()}\n")
            md_parts.append("\n")
        elif tag_name == "a":
            href = child.get("href", "")
            if href and text:
                md_parts.append(f"[{text}]({href})")
            else:
                md_parts.append(text)
        elif tag_name == "img":
            src = child.get("data-src") or child.get("src") or ""
            if src:
                md_parts.append(f"\n![图片]({src})\n")
        elif tag_name in (
            "section", "div", "span", "figure", "td", "tr",
            "main", "article", "html", "body",
        ):
            md_parts.append(html_to_markdown(child, depth + 1))
        elif text:
            md_parts.append(text)

    return re.sub(r"\n{4,}", "\n\n", "".join(md_parts)).strip()


def _regex_fallback(html: str, url: str) -> DistilledContent:
    """无 bs4 时的粗暴降级：正则剥标签（保底不崩，质量差）。"""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return DistilledContent(
        url=url,
        content_text=text,
        stats={"raw_chars": len(html), "distilled_chars": len(text), "mode": "regex-fallback"},
    )


def distill(
    html: str,
    url: str = "",
    *,
    content_selectors: list[str] | None = None,
    meta_selectors: dict[str, list[str]] | None = None,
) -> DistilledContent:
    """HTML → DistilledContent（统一入口）。

    - content_selectors: 平台特异正文容器选择器（置于通用候选之前）
    - meta_selectors: 平台特异元数据选择器（与通用候选合并、优先）
    """
    if not _HAS_BS4:
        return _regex_fallback(html, url)

    soup = BeautifulSoup(html, "html.parser")

    # 元数据在剥离噪声前提取（og: meta 在 head 内，噪声剥离不影响，但保持顺序稳定）
    meta = extract_metadata(soup, html, meta_selectors)

    # 正文定位：先定位再剥离容器外噪声（容器定位本身已跳过导航等）
    content = locate_content(soup, content_selectors)
    if content is not None:
        strip_noise(content)
        markdown = html_to_markdown(content)
        content_text = content.get_text(separator="\n", strip=True)
    else:
        # 无命中容器：全页剥离噪声后取 body
        strip_noise(soup)
        body = soup.body or soup
        markdown = html_to_markdown(body)
        content_text = body.get_text(separator="\n", strip=True)

    raw_chars = len(html)
    distilled_chars = len(markdown)
    reduction = 1.0 - (distilled_chars / raw_chars) if raw_chars else 0.0
    stats = {
        "raw_chars": raw_chars,
        "distilled_chars": distilled_chars,
        "reduction_ratio": round(reduction, 4),
        "container_found": content is not None,
    }
    return DistilledContent(
        url=url,
        title=meta["title"],
        author=meta["author"],
        publish_time=meta["publish_time"],
        markdown=markdown,
        content_text=content_text,
        stats=stats,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="HTML → 干净 Markdown（共享蒸馏引擎）")
    parser.add_argument("--url", default="", help="来源 URL（写入元数据）")
    parser.add_argument("--file", help="HTML 文件路径（缺省读 stdin）")
    parser.add_argument("--json", action="store_true", help="JSON 输出（含 stats）")
    args = parser.parse_args()

    if args.file:
        html = open(args.file, encoding="utf-8", errors="ignore").read()
    else:
        html = sys.stdin.read()

    if not html.strip():
        print("错误：输入为空", file=sys.stderr)
        return 1

    result = distill(html, args.url)
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if result.title:
        print(f"# {result.title}\n")
    print(result.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
