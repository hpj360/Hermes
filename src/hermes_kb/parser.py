"""文档解析 + 分片。

支持格式：txt / md / pdf
分片策略：段落优先 + 滑动窗口重叠
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParsedDocument:
    """解析后的文档。"""

    title: str
    content: str  # 已剥离 md 标记的纯文本
    file_type: str


class DocumentParser:
    """文档解析器。"""

    def parse_file(self, path: str | Path) -> ParsedDocument:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        suffix = p.suffix.lstrip(".").lower()
        if suffix == "txt":
            text = p.read_text(encoding="utf-8", errors="ignore")
            ft = "txt"
        elif suffix in ("md", "markdown"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            ft = "md"
        elif suffix == "pdf":
            text = self._parse_pdf(p)
            ft = "pdf"
        else:
            # 默认按文本处理
            text = p.read_text(encoding="utf-8", errors="ignore")
            ft = "txt"
        title = p.stem
        if ft == "md":
            text = self._strip_markdown(text)
        return ParsedDocument(title=title, content=text, file_type=ft)

    def parse_text(self, content: str, file_type: str = "txt", title: str = "") -> ParsedDocument:
        if file_type == "md":
            content = self._strip_markdown(content)
        return ParsedDocument(title=title or "untitled", content=content, file_type=file_type)

    def _parse_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("pypdf 未安装，无法解析 PDF") from e
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t:
                parts.append(t)
        return "\n\n".join(parts)

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """剥离 Markdown 标记为纯文本。"""
        # 标题
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # 代码块
        text = re.sub(r"```[\s\S]*?```", "", text)
        # 行内代码
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # 图片
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        # 链接
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # 粗体/斜体
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        # 列表标记
        text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
        # 引用
        text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)
        # 水平线
        text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
        return text

    def chunk(
        self,
        text: str,
        chunk_size: int = 500,
        overlap: int = 80,
    ) -> list[tuple[int, int, str]]:
        """分片：返回 [(char_start, char_end, chunk_text), ...]。

        策略：先按段落切分，超长段落按 chunk_size 滑窗，相邻片段重叠 overlap 字符。
        """
        if not text or not text.strip():
            return []
        chunk_size = max(50, chunk_size)
        overlap = max(0, min(overlap, chunk_size // 2))

        # 按双换行切段
        paragraphs = re.split(r"\n\s*\n", text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks: list[tuple[int, int, str]] = []
        cursor = 0  # 原文本中的位置
        buffer = ""
        buf_start = 0

        def flush_buffer():
            nonlocal buffer, buf_start
            if not buffer.strip():
                buffer = ""
                return
            # 切分 buffer
            if len(buffer) <= chunk_size:
                chunks.append((buf_start, buf_start + len(buffer), buffer))
                buffer = ""
            else:
                # 滑窗
                i = 0
                while i < len(buffer):
                    end = min(i + chunk_size, len(buffer))
                    piece = buffer[i:end]
                    chunks.append((buf_start + i, buf_start + end, piece))
                    if end >= len(buffer):
                        break
                    i = end - overlap
                buffer = ""

        for para in paragraphs:
            # 找到 para 在原 text 中的位置（从 cursor 开始）
            idx = text.find(para, cursor)
            if idx < 0:
                idx = cursor
            para_start = idx
            para_end = idx + len(para)
            cursor = para_end

            if buffer and len(buffer) + len(para) + 1 > chunk_size + overlap:
                flush_buffer()
                buf_start = para_start
                buffer = para
            else:
                if not buffer:
                    buf_start = para_start
                    buffer = para
                else:
                    buffer += "\n" + para
        flush_buffer()
        return chunks
