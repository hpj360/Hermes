"""P0.5: Capture notes — write inbox entries to the Obsidian notes vault.

Captured ideas / links / facts are persisted as markdown files under
``HERMES_NOTES_DIR`` (default ``D:\\Hermes\\notes``), the only sub-tree of the
Obsidian vault that is git-tracked (PRD D-D). Writing is synchronous and
fail-safe: a capture must never be lost even if the async summary job fails.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


__all__ = ["NoteEntry", "NotesStore", "slugify"]


def slugify(text: str, max_len: int = 40) -> str:
    """Produce a filesystem-safe slug from free text."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        text = "note"
    return text[:max_len] or "note"


@dataclass(frozen=True)
class NoteEntry:
    """A parsed vault note (frontmatter + heading + snippet + tags)."""

    id: str
    title: str
    type: str
    source: str
    created_at: str
    path: str
    tags: list[str] = field(default_factory=list)
    snippet: str = ""
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "source": self.source,
            "created_at": self.created_at,
            "path": self.path,
            "tags": list(self.tags),
            "snippet": self.snippet,
            "url": self.url,
        }


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_TAG_RE = re.compile(r"(?<!\w)#([\w\u4e00-\u9fff-]+)")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split *text* into (frontmatter mapping, remaining body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, text[match.end():]


def _parse_note(path: Path, notes_dir: Path) -> NoteEntry:
    """Parse a markdown note into a :class:`NoteEntry`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    meta, body = _parse_frontmatter(text)

    title = ""
    url: str | None = None
    body_lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if stripped.startswith("原文链接:"):
            url = stripped.split(":", 1)[1].strip() or None
            continue
        body_lines.append(line)
    if not title:
        title = path.stem

    snippet = " ".join(part.strip() for part in body_lines if part.strip())[:200]

    tags: list[str] = []
    if meta.get("tags"):
        tags = [t.strip() for t in re.split(r"[,\s]+", meta["tags"]) if t.strip()]
    else:
        tags = _TAG_RE.findall(body)
    tags = list(dict.fromkeys(tags))

    try:
        rel = str(path.relative_to(notes_dir))
    except ValueError:
        rel = str(path)

    return NoteEntry(
        id=meta.get("id", path.stem),
        title=title,
        type=meta.get("type", "note"),
        source=meta.get("source", "manual"),
        created_at=meta.get("created_at", ""),
        path=rel,
        tags=tags,
        snippet=snippet,
        url=url,
    )



class NotesStore:
    """Writes capture entries as markdown under ``notes/inbox/<YYYY-MM>/``."""

    def __init__(self, notes_dir: Path | str) -> None:
        self.notes_dir = Path(notes_dir)
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def note_path(self, todo_id: str, title: str) -> Path:
        """Resolve the note file path for a capture (idempotent)."""
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return self.notes_dir / "inbox" / month / f"{todo_id}-{slugify(title)}.md"

    def write(self, todo_id: str, title: str, *, type_: str = "idea",
              body: str = "", url: str | None = None, source: str = "manual",
              created_at: str | None = None) -> Path:
        """Write (or overwrite) the markdown note for a capture.

        Returns the written path. Markdown frontmatter keeps the entry
        machine-readable; the body carries the link/text content so the vault
        note stays self-contained.
        """
        path = self.note_path(todo_id, title)
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = created_at or datetime.now(timezone.utc).isoformat()
        lines = [
            "---",
            f"id: {todo_id}",
            f"type: {type_}",
            f"source: {source}",
            f"created_at: {ts}",
            "---",
            "",
            f"# {title}",
            "",
        ]
        if url:
            lines += [f"原文链接: {url}", ""]
        if body:
            lines += [body.strip(), ""]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def resolve(self, todo_id: str) -> Path | None:
        """Return the note file for *todo_id* if it exists, else None."""
        for candidate in self.notes_dir.rglob(f"{todo_id}-*.md"):
            return candidate
        return None

    def summary(self) -> dict[str, Any]:
        """Return a lightweight vault index summary."""
        notes = list(self.notes_dir.rglob("*.md"))
        return {"notes_dir": str(self.notes_dir), "note_count": len(notes)}

    # ------------------------------------------------------------------
    # C6: vault 内容索引 + 检索 + 知识卡
    # ------------------------------------------------------------------

    def index(self, *, limit: int | None = None) -> list[NoteEntry]:
        """Parse all vault notes into :class:`NoteEntry` (newest first)."""
        entries = [
            _parse_note(p, self.notes_dir)
            for p in self.notes_dir.rglob("*.md")
            if p.is_file()
        ]
        entries.sort(key=lambda e: (e.created_at, e.path), reverse=True)
        return entries[:limit] if limit is not None else entries

    def search(self, query: str, *, limit: int = 20) -> list[NoteEntry]:
        """Keyword search across title/tags/body.

        Case-insensitive; multiple whitespace-separated terms are OR-ed and
        weighted (title 3, tags 2, body 1). Returns entries sorted by score.
        """
        terms = [t.lower() for t in (query or "").split() if t.strip()]
        if not terms:
            return []
        scored: list[tuple[int, NoteEntry]] = []
        for entry in self.index():
            haystack_title = entry.title.lower()
            haystack_tags = " ".join(entry.tags).lower()
            haystack_body = entry.snippet.lower()
            score = 0
            for term in terms:
                if term in haystack_title:
                    score += 3
                if term in haystack_tags:
                    score += 2
                if term in haystack_body:
                    score += 1
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def knowledge_card(
        self, keywords: list[str], *, limit: int = 5
    ) -> dict[str, Any]:
        """Build a creation-workbench knowledge card from *keywords*.

        Returns related vault notes (title/snippet/tags/path/url) so the
        content workbench can surface prior material before创作.
        """
        cleaned = [k.strip() for k in (keywords or []) if k and k.strip()]
        seen: set[str] = set()
        related: list[NoteEntry] = []
        for kw in cleaned:
            for entry in self.search(kw, limit=limit):
                if entry.path not in seen:
                    seen.add(entry.path)
                    related.append(entry)
                if len(related) >= limit:
                    break
            if len(related) >= limit:
                break
        return {
            "keywords": cleaned,
            "note_count": len(related),
            "related_notes": [e.to_dict() for e in related],
        }

