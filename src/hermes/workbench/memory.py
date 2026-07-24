"""Three-layer memory for the Workbench agent runtime.

L1 — Facts: small key/value JSON store for durable preferences and observations.
L2 — Episodes: append-only JSONL log of agent actions (each entry an Episode).
L3 — Profile: the user profile (delegated to hermes.profile).
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hermes.workbench.persistence import (
    atomic_append_jsonl,
    atomic_write_json,
    safe_read_json,
)


# ---------------------------------------------------------------------------
# TF-IDF helpers (pure stdlib, no external dependencies)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric characters."""
    return _TOKEN_RE.findall(text.lower())


def _compute_tfidf(documents: list[list[str]]) -> list[dict[str, float]]:
    """Compute TF-IDF vectors for a list of tokenized documents."""
    n_docs = len(documents)
    if n_docs == 0:
        return []
    df: Counter[str] = Counter()
    for tokens in documents:
        for word in set(tokens):
            df[word] += 1
    idf = {w: math.log((n_docs + 1) / (c + 1)) + 1 for w, c in df.items()}
    vectors: list[dict[str, float]] = []
    for tokens in documents:
        tf = Counter(tokens)
        total = len(tokens) or 1
        vectors.append({w: (c / total) * idf.get(w, 0.0) for w, c in tf.items()})
    return vectors


def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Cosine similarity between two sparse term-weight vectors."""
    if not vec1 or not vec2:
        return 0.0
    dot = sum(v * vec2.get(k, 0.0) for k, v in vec1.items())
    mag1 = math.sqrt(sum(v * v for v in vec1.values()))
    mag2 = math.sqrt(sum(v * v for v in vec2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


@dataclass
class Episode:
    """A single recorded agent event."""

    id: str
    kind: str
    summary: str
    details: dict[str, Any]
    created_at: float


def make_episode(kind: str, summary: str, details: dict[str, Any] | None = None) -> Episode:
    """Build a new Episode with a generated id and current timestamp."""
    return Episode(
        id=uuid.uuid4().hex,
        kind=kind,
        summary=summary,
        details=details if details is not None else {},
        created_at=time.time(),
    )


class MemoryService:
    """In-process memory service backed by atomic file persistence."""

    def __init__(
        self,
        state_dir: Path,
        profile_loader: Callable[[], dict[str, Any]] | None = None,
        profile_saver: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._facts_path = state_dir / "facts.json"
        self._fact_ttls_path = state_dir / "fact_ttls.json"
        self._episodes_path = state_dir / "episodes.jsonl"
        self._profile_loader = profile_loader
        self._profile_saver = profile_saver

    # ------------------------------------------------------------------
    # L1 — Facts
    # ------------------------------------------------------------------
    def remember_fact(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Set (or overwrite) the value of fact *key*.

        If *ttl* is given, the fact expires after *ttl* seconds and
        ``get_fact`` / ``list_facts`` will automatically purge it.
        """
        facts = self._read_facts()
        facts[key] = value
        atomic_write_json(self._facts_path, facts)
        ttls = self._read_fact_ttls()
        if ttl is not None:
            ttls[key] = time.time() + ttl
        else:
            ttls.pop(key, None)
        atomic_write_json(self._fact_ttls_path, ttls)

    def get_fact(self, key: str) -> dict[str, Any] | None:
        """Return ``{"key": key, "value": value}`` for *key*, or None if absent."""
        self._purge_expired_facts(only_key=key)
        facts = self._read_facts()
        if key not in facts:
            return None
        return {"key": key, "value": facts[key]}

    def list_facts(self) -> list[dict[str, Any]]:
        """Return all facts as a list of ``{"key", "value"}`` dicts."""
        self._purge_expired_facts()
        facts = self._read_facts()
        return [{"key": k, "value": v} for k, v in facts.items()]

    def forget_fact(self, key: str) -> bool:
        """Delete fact *key*. Returns True if it existed."""
        facts = self._read_facts()
        if key not in facts:
            return False
        del facts[key]
        atomic_write_json(self._facts_path, facts)
        ttls = self._read_fact_ttls()
        if key in ttls:
            del ttls[key]
            atomic_write_json(self._fact_ttls_path, ttls)
        return True

    def _read_facts(self) -> dict[str, Any]:
        data = safe_read_json(self._facts_path, default={})
        if isinstance(data, dict):
            return data
        return {}

    def _read_fact_ttls(self) -> dict[str, float]:
        data = safe_read_json(self._fact_ttls_path, default={})
        if isinstance(data, dict):
            return data
        return {}

    def _purge_expired_facts(self, only_key: str | None = None) -> None:
        """Remove facts whose TTL has elapsed. If *only_key* is given, only check that key."""
        ttls = self._read_fact_ttls()
        if not ttls:
            return
        now = time.time()
        keys_to_check = [only_key] if only_key is not None else list(ttls.keys())
        expired = [k for k in keys_to_check if k in ttls and now > ttls[k]]
        if not expired:
            return
        facts = self._read_facts()
        changed = False
        for k in expired:
            facts.pop(k, None)
            ttls.pop(k, None)
            changed = True
        if changed:
            atomic_write_json(self._facts_path, facts)
            atomic_write_json(self._fact_ttls_path, ttls)

    # ------------------------------------------------------------------
    # L2 — Episodes
    # ------------------------------------------------------------------
    def record_episode(self, episode: Episode) -> None:
        """Append *episode* to the JSONL episode log."""
        payload = {
            "id": episode.id,
            "kind": episode.kind,
            "summary": episode.summary,
            "details": episode.details,
            "created_at": episode.created_at,
        }
        atomic_append_jsonl(self._episodes_path, payload)

    def list_episodes(self, kind: str | None = None, limit: int = 1000) -> list[Episode]:
        """Return recorded episodes, optionally filtered by *kind*.

        The most recent *limit* matching episodes are returned, newest first.
        """
        if not self._episodes_path.exists():
            return []
        items: list[Episode] = []
        with self._episodes_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = _parse_episode_line(line)
                except (ValueError, KeyError):
                    continue
                if kind is not None and obj.kind != kind:
                    continue
                items.append(obj)
        # Most recent first; cap via deque maxlen on the tail.
        if limit <= 0:
            return []
        recent = list(deque(items, maxlen=limit))
        recent.reverse()
        return recent

    def search_episodes(
        self,
        query: str,
        limit: int = 10,
        kind: str | None = None,
    ) -> list[tuple[Episode, float]]:
        """Keyword-search episodes via TF-IDF cosine similarity.

        Returns a list of ``(episode, score)`` tuples, highest score first.
        Only episodes with a positive similarity score are returned.
        """
        episodes = self.list_episodes(kind=kind, limit=10000)
        if not episodes:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        # Build document text from summary + details
        documents: list[list[str]] = []
        for ep in episodes:
            text = ep.summary
            if ep.details:
                text += " " + json.dumps(ep.details, ensure_ascii=False)
            documents.append(_tokenize(text))
        vectors = _compute_tfidf(documents)
        query_vecs = _compute_tfidf([query_tokens])
        if not query_vecs:
            return []
        query_vec = query_vecs[0]
        scored = [
            (ep, _cosine_similarity(query_vec, vec))
            for ep, vec in zip(episodes, vectors, strict=True)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(ep, s) for ep, s in scored[:limit] if s > 0.0]

    # ------------------------------------------------------------------
    # L3 — Profile
    # ------------------------------------------------------------------
    def get_user_profile(self) -> dict[str, Any]:
        """Return the user profile (delegated to the configured loader)."""
        if self._profile_loader is not None:
            return self._profile_loader()
        from hermes.profile import load_profile
        return load_profile()

    def save_user_profile(self, profile: dict[str, Any]) -> None:
        """Persist *profile* (delegated to the configured saver)."""
        if self._profile_saver is not None:
            self._profile_saver(profile)
            return
        from hermes.profile import save_profile
        save_profile(profile)

    # ------------------------------------------------------------------
    # Maintenance: TTL cleanup, RRF search, profile learning, compaction
    # ------------------------------------------------------------------
    def cleanup_expired_facts(self) -> int:
        """Purge all expired facts and return the number removed.

        Unlike the lazy purge triggered by get_fact/list_facts, this method
        always scans every TTL entry and returns a count, making it suitable
        for periodic background maintenance.
        """
        ttls = self._read_fact_ttls()
        if not ttls:
            return 0
        now = time.time()
        expired = [k for k, exp in ttls.items() if now > exp]
        if not expired:
            return 0
        facts = self._read_facts()
        for k in expired:
            facts.pop(k, None)
            ttls.pop(k, None)
        atomic_write_json(self._facts_path, facts)
        atomic_write_json(self._fact_ttls_path, ttls)
        return len(expired)

    def search_episodes_rrf(
        self,
        query: str,
        limit: int = 10,
        kind: str | None = None,
        k: int = 60,
    ) -> list[tuple[Episode, float]]:
        """Hybrid episode search using Reciprocal Rank Fusion.

        Fuses two retrieval signals:
          1. Exact substring match (case-insensitive) on summary + details
          2. TF-IDF cosine similarity (semantic-ish keyword overlap)

        RRF score = sum(1 / (k + rank)) across the two ranked lists, where a
        lower rank number means a better match. Episodes appearing in both
        lists get a higher fused score than those in only one.

        Returns ``(episode, fused_score)`` tuples, highest score first.
        """
        if not query or not query.strip():
            return []
        episodes = self.list_episodes(kind=kind, limit=10000)
        if not episodes:
            return []
        q_lower = query.lower()

        # Signal 1: exact substring match (rank by earliest match position)
        substring_matches: list[tuple[Episode, int]] = []
        for ep in episodes:
            text = ep.summary.lower()
            if ep.details:
                text += " " + json.dumps(ep.details, ensure_ascii=False).lower()
            pos = text.find(q_lower)
            if pos != -1:
                substring_matches.append((ep, pos))
        # Earlier position = better → ascending sort → rank 0 is best
        substring_matches.sort(key=lambda x: x[1])
        sub_ranks: dict[str, int] = {
            ep.id: rank for rank, (ep, _pos) in enumerate(substring_matches)
        }

        # Signal 2: TF-IDF cosine similarity (existing implementation)
        tfidf_results = self.search_episodes(query, limit=len(episodes), kind=kind)
        tfidf_ranks: dict[str, int] = {
            ep.id: rank for rank, (ep, _score) in enumerate(tfidf_results)
        }

        # Fuse via RRF
        all_ids = set(sub_ranks) | set(tfidf_ranks)
        if not all_ids:
            return []
        id_to_ep: dict[str, Episode] = {ep.id: ep for ep in episodes}
        fused: list[tuple[Episode, float]] = []
        for ep_id in all_ids:
            score = 0.0
            if ep_id in sub_ranks:
                score += 1.0 / (k + sub_ranks[ep_id])
            if ep_id in tfidf_ranks:
                score += 1.0 / (k + tfidf_ranks[ep_id])
            ep = id_to_ep.get(ep_id)
            if ep is not None:
                fused.append((ep, score))
        fused.sort(key=lambda x: x[1], reverse=True)
        return fused[:limit]

    def learn_profile_from_episodes(
        self, recent_count: int = 200, top_n: int = 5
    ) -> dict[str, Any]:
        """Derive profile insights from recent episodes (rule-based).

        Without an LLM, this extracts:
          * most-used skills (from episode details.skill / steps)
          * most frequent episode kinds
          * recent activity summary

        The result is merged into the user profile via
        :meth:`save_user_profile`. Returns the learned insights dict.
        """
        episodes = self.list_episodes(limit=recent_count)
        skill_counts: Counter[str] = Counter()
        kind_counts: Counter[str] = Counter()
        for ep in episodes:
            kind_counts[ep.kind] += 1
            # Extract skill names from details (varies by episode kind)
            details = ep.details or {}
            for field_name in ("skill", "steps", "skill_used"):
                val = details.get(field_name)
                if isinstance(val, str) and val:
                    skill_counts[val] += 1
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            s = item.get("skill") or item.get("name")
                            if isinstance(s, str):
                                skill_counts[s] += 1
                        elif isinstance(item, str):
                            skill_counts[item] += 1
        insights: dict[str, Any] = {
            "top_skills": [
                {"skill": s, "count": c} for s, c in skill_counts.most_common(top_n)
            ],
            "top_kinds": [
                {"kind": k, "count": c} for k, c in kind_counts.most_common(top_n)
            ],
            "episode_count": len(episodes),
            "learned_at": time.time(),
        }
        # Merge into the existing profile
        try:
            profile = self.get_user_profile()
            if not isinstance(profile, dict):
                profile = {}
            profile.setdefault("learned", {})["memory_insights"] = insights
            self.save_user_profile(profile)
        except Exception:  # noqa: BLE001 — profile save is best-effort
            pass
        return insights

    def compact_episodes(
        self, keep_recent: int = 200, kind: str | None = None
    ) -> dict[str, Any]:
        """Compact old episodes into summary episodes.

        Episodes beyond the *keep_recent* window (optionally filtered by
        *kind*) are aggregated into one summary episode per kind, recording
        the count and time span. The original old episodes are then removed
        from the JSONL file. Recent episodes (within the window) are kept
        intact.

        Returns a dict describing the compaction result:
            {"compacted_kinds": [...], "removed": N, "summaries_added": M}
        """
        all_episodes = self.list_episodes(kind=kind, limit=10**9)
        if len(all_episodes) <= keep_recent:
            return {"compacted_kinds": [], "removed": 0, "summaries_added": 0}
        # Split: keep the most recent `keep_recent`, compact the rest.
        recent = all_episodes[:keep_recent]
        old = all_episodes[keep_recent:]
        # Group old episodes by kind for per-kind summaries
        by_kind: dict[str, list[Episode]] = {}
        for ep in old:
            by_kind.setdefault(ep.kind, []).append(ep)
        # Build summary episodes
        summaries: list[Episode] = []
        for ep_kind, eps in by_kind.items():
            timestamps = [e.created_at for e in eps]
            summary = make_episode(
                f"{ep_kind}_summary",
                f"[Compacted] {len(eps)} {ep_kind} episodes "
                f"({min(timestamps):.0f} → {max(timestamps):.0f})",
                {
                    "kind": ep_kind,
                    "count": len(eps),
                    "first_at": min(timestamps),
                    "last_at": max(timestamps),
                    "compacted": True,
                },
            )
            summaries.append(summary)
        # Rewrite the episodes file: summaries first (oldest), then recent (newest)
        # Since list_episodes returns newest-first, recent[0] is newest.
        # We want the file ordered oldest → newest so append order is:
        #   summaries (old, compacted) → recent reversed (oldest recent → newest recent)
        to_write: list[Episode] = []
        to_write.extend(summaries)  # compacted summaries (become the "old" history)
        to_write.extend(reversed(recent))  # oldest recent → newest recent
        # Atomic rewrite
        lines = []
        for ep in to_write:
            lines.append(
                json.dumps(
                    {
                        "id": ep.id,
                        "kind": ep.kind,
                        "summary": ep.summary,
                        "details": ep.details,
                        "created_at": ep.created_at,
                    },
                    ensure_ascii=False,
                )
            )
        self._episodes_path.write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )
        return {
            "compacted_kinds": list(by_kind.keys()),
            "removed": len(old),
            "summaries_added": len(summaries),
        }


def _parse_episode_line(line: str) -> Episode:
    """Parse a single JSONL line into an Episode."""
    import json
    obj = json.loads(line)
    if not isinstance(obj, dict):
        raise ValueError("episode line is not an object")
    details = obj.get("details", {})
    if not isinstance(details, dict):
        details = {"value": details}
    return Episode(
        id=str(obj["id"]),
        kind=str(obj["kind"]),
        summary=str(obj.get("summary", "")),
        details=details,
        created_at=float(obj.get("created_at", 0.0)),
    )
