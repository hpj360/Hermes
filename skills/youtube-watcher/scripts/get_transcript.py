#!/usr/bin/env python3
"""YouTube 字幕转写提取器。

输出契约（统一）：默认人类可读报告 / ``--json`` 机器模式 / ``-o <file>`` 写文件。
报告渲染与输出契约由 content-extraction 共享引擎提供。
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# 寻址共享引擎（报告渲染统一契约）
_ENGINE_DIR = Path(__file__).resolve().parents[2] / "content-extraction" / "scripts"
sys.path.insert(0, str(_ENGINE_DIR))
from report import emit, render_report  # noqa: E402


def clean_vtt(content: str) -> str:
    """
    Clean WebVTT content to plain text.
    Removes headers, timestamps, and duplicate lines.
    """
    lines = content.splitlines()
    text_lines = []

    timestamp_pattern = re.compile(r'\d{2}:\d{2}:\d{2}\.\d{3}\s-->\s\d{2}:\d{2}:\d{2}\.\d{3}')

    for line in lines:
        line = line.strip()
        if not line or line == 'WEBVTT' or line.isdigit():
            continue
        if timestamp_pattern.match(line):
            continue
        if line.startswith('NOTE') or line.startswith('STYLE'):
            continue

        if text_lines and text_lines[-1] == line:
            continue

        line = re.sub(r'<[^>]+>', '', line)

        text_lines.append(line)

    return '\n'.join(text_lines)


def get_transcript(url: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        cmd = [
            "yt-dlp",
            "--write-subs",
            "--write-auto-subs",
            "--skip-download",
            "--sub-lang", "en",
            "--output", "subs",
            url
        ]

        try:
            subprocess.run(cmd, cwd=temp_dir, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running yt-dlp: {e.stderr.decode()}", file=sys.stderr)
            sys.exit(1)
        except FileNotFoundError:
            print("Error: yt-dlp not found. Please install it.", file=sys.stderr)
            sys.exit(1)

        temp_path = Path(temp_dir)
        vtt_files = list(temp_path.glob("*.vtt"))

        if not vtt_files:
            print("No subtitles found.", file=sys.stderr)
            sys.exit(1)

        vtt_file = vtt_files[0]
        content = vtt_file.read_text(encoding='utf-8')
        clean = clean_vtt(content)
        stats = {
            "raw_chars": len(content),
            "distilled_chars": len(clean),
            "reduction_ratio": round(1 - len(clean) / len(content), 4) if content else 0.0,
        }
        return clean, stats


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube transcript.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("-o", "--output", default="", help="写入文件（默认 stdout）")
    args = parser.parse_args()

    clean_text, stats = get_transcript(args.url)

    payload = {"url": args.url, "transcript": clean_text, "stats": stats}
    report = render_report(
        title="YouTube 转写",
        meta={"来源": "YouTube", "URL": args.url, "语言": "en"},
        body=clean_text,
        stats=stats,
    )
    sys.exit(emit(payload, report, fmt="json" if args.json else "report", output=args.output))


if __name__ == "__main__":
    main()
