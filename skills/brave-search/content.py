#!/usr/bin/env python3
"""通用网页内容提取（brave-search 主路径）。

获取层（本文件）：UA 伪装 + 15s 超时 + HTTP 状态校验（平台特异）。
清洗/表现层：共享蒸馏引擎 content-extraction（distill + report）。
node-only 环境可用同目录 content.js（JS 降级实现，质量以本路径为准）。

用法：
    python3 content.py <url> [--json] [--concise] [-o <文件>]
"""
import argparse
import sys
import urllib.request
from pathlib import Path

_ENGINE_DIR = Path(__file__).resolve().parents[2] / "content-extraction" / "scripts"
sys.path.insert(0, str(_ENGINE_DIR))
from distill import distill  # noqa: E402
from report import emit, render_report  # noqa: E402

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract readable content as markdown.")
    parser.add_argument("url", help="Page URL")
    parser.add_argument("--json", action="store_true", help="JSON 输出（含 stats）")
    parser.add_argument("--concise", action="store_true", help="极简档（面向人的交互回复）")
    parser.add_argument("-o", "--output", default="", help="写入文件（默认 stdout）")
    args = parser.parse_args()

    try:
        html = fetch_html(args.url)
    except Exception as e:  # noqa: BLE001 - CLI 边界统一报错
        print(f"Error: {e}", file=sys.stderr)
        return 1

    result = distill(html, args.url)
    payload = result.to_dict()
    report = render_report(
        title=result.title,
        meta={"来源": args.url},
        body=result.markdown,
        stats=result.stats,
        style="concise" if args.concise else "report",
    )
    return emit(payload, report, fmt="json" if args.json else "report", output=args.output)


if __name__ == "__main__":
    sys.exit(main())
