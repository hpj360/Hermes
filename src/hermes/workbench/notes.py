"""P0.5: Capture notes — write inbox entries to the Obsidian notes vault.

Captured ideas / links / facts are persisted as markdown files under
``HERMES_NOTES_DIR`` (default ``D:\\Hermes\\notes``), the only sub-tree of the
Obsidian vault that is git-tracked (PRD D-D). Writing is synchronous and
fail-safe: a capture must never be lost even if the async summary job fails.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


__all__ = ["NotesStore", "slugify"]


def slugify(text: str, max_len: int = 40) -> str:
    """Produce a filesystem-safe slug from free text."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text.lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        text = "note"
    return text[:max_len] or "note"


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
