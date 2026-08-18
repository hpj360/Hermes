"""Cache-aware context maintenance (Reasonix borrow — A1/A3).

Three concerns:

1. ``env_summary`` — a stable, versioned snapshot of the repository's conventions
   and structure, cached so it is computed once (not re-derived every turn) and
   only rebuilt when its content hash changes. Keeping it stable is what makes
   the LLM's prompt prefix cache-friendly.

2. ``build_stable_prefix`` — assemble the *stable* prompt prefix (agent
   definition + environment summary) in a fixed order with no volatile content
   (no timestamps, no per-round checker reports). The volatile suffix (task +
   context) is kept separate so it never invalidates the cached prefix.

3. ``prune_stale_tool_outputs`` — drop tool outputs that no longer carry a
   kept marker (e.g. a stale file read superseded by a later edit) before
   compaction/summarization, so context does not grow monotonically.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from hermes.workbench.persistence import atomic_write_json, safe_read_json

# Marker lines that identify a tool output as still-relevant (kept during prune).
_DEFAULT_KEPT_MARKERS = ("ALL GREEN", "FAILED", "error", "Error")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _summary_dir() -> Path:
    from hermes.config import get_settings

    s = get_settings()
    if s.hermes_context_summary_dir:
        return Path(s.hermes_context_summary_dir)
    return s.hermes_cache_dir


def _conventions_text(repo_root: Path) -> str:
    """Read the repo's convention files (AGENTS.md / CLAUDE.md) into one string."""
    parts: list[str] = []
    for name in ("AGENTS.md", "CLAUDE.md", "CONTEXT.md"):
        p = repo_root / name
        if p.is_file():
            parts.append(f"# {name}\n{p.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _structure_lines(repo_root: Path) -> list[str]:
    """Top-level directory names (stable, sorted) — a cheap repo fingerprint."""
    if not repo_root.is_dir():
        return []
    return sorted(
        child.name for child in repo_root.iterdir() if child.is_dir()
    )


def env_summary(repo_root: Path) -> dict[str, Any]:
    """Return a stable, cached environment summary.

    The summary is ``{"version": <sha256>, "conventions": <text>,
    "structure": [<dir names>]}``. It is cached to ``<summary_dir>/
    context-summary.json``; the cache is only rewritten when the source content
    hash changes, so the summary is byte-stable across turns.
    """
    conventions = _conventions_text(repo_root)
    structure = _structure_lines(repo_root)
    version = _hash_text(conventions + "\n" + "\n".join(structure))
    cache_path = _summary_dir() / "context-summary.json"
    cached = safe_read_json(cache_path, default=None)
    if isinstance(cached, dict) and cached.get("version") == version:
        return cached
    summary = {
        "version": version,
        "conventions": conventions,
        "structure": structure,
    }
    try:
        atomic_write_json(cache_path, summary)
    except OSError:
        pass  # cache write is best-effort; return the in-memory summary anyway
    return summary


def build_stable_prefix(
    agent_definition: str, env: dict[str, Any] | None = None, repo_root: Path | None = None
) -> str:
    """Assemble the stable prompt prefix (fixed order, no volatile content).

    Order: agent definition, then the environment summary. ``env`` defaults to
    ``env_summary(repo_root)``; ``repo_root`` defaults to the project root.
    """
    if env is None:
        root = repo_root if repo_root is not None else _project_root()
        env = env_summary(root)
    parts = [agent_definition] if agent_definition else []
    if env.get("conventions"):
        parts.append("# Environment\n" + str(env["conventions"]))
    return "\n\n".join(parts)


def assert_stable_prefix(prefix_a: str, prefix_b: str) -> None:
    """Contract: the stable prefix must be identical across turns.

    Raises ``ValueError`` when a supposedly-stable prefix changed — this catches
    accidental injection of volatile content (timestamps, dynamic ids) into the
    cacheable region.
    """
    if prefix_a != prefix_b:
        raise ValueError(
            "stable prefix changed across rounds — volatile content leaked into "
            "the cacheable prefix"
        )


def prune_stale_tool_outputs(
    messages: list[dict[str, Any]],
    kept_markers: list[str] | None = None,
    keep_last: int = 5,
) -> list[dict[str, Any]]:
    """Drop stale tool outputs, keeping marker hits and the last ``keep_last``.

    A message is treated as a tool output when ``role == "tool"`` or it carries
    a ``tool_call_id``/``name`` key. Tool outputs whose text matches no marker
    and are not among the trailing ``keep_last`` messages are pruned (replaced
    with a short ``[stale tool output pruned]`` note is NOT done — they are
    simply dropped) so context does not grow monotonically.
    """
    markers = kept_markers if kept_markers is not None else _DEFAULT_KEPT_MARKERS
    kept: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        is_tool = msg.get("role") == "tool" or "tool_call_id" in msg or "name" in msg
        if not is_tool:
            kept.append(msg)
            continue
        content = str(msg.get("content", ""))
        if any(marker in content for marker in markers) or i >= len(messages) - keep_last:
            kept.append(msg)
    return kept


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]
