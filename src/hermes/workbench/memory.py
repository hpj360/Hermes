"""Three-layer memory for the Workbench agent runtime.

L1 — Facts: small key/value JSON store for durable preferences and observations.
L2 — Episodes: append-only JSONL log of agent actions (each entry an Episode).
L3 — Profile: the user profile (delegated to hermes.profile).

Enhanced with:
- FTS5 full-text search via sqlite3 (zero external deps)
- Ollama-compatible vector embedding for semantic search
- Multi-level memory compaction (L1 raw → L2 grouped → L3 abstract)
- MemOS local plugin adapter (optional, HTTP client to :18800)
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes.workbench.persistence import (
    atomic_append_jsonl,
    atomic_write_json,
    safe_read_json,
)

logger = logging.getLogger("hermes.workbench.memory")

# ---------------------------------------------------------------------------
# TF-IDF helpers (pure stdlib, no external dependencies)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\w+")

# Guards concurrent first-touch schema creation on the FTS5 index.
_FTS_SCHEMA_LOCK = threading.Lock()


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
    """In-process memory service backed by atomic file persistence.

    Enhanced with:
    - FTS5 full-text search (sqlite3, zero external deps)
    - Optional vector embedding (Ollama-compatible)
    - Optional MemOS adapter (local plugin on :18800)
    - Multi-level compaction (L1 raw → L2 grouped → L3 abstract)
    """

    def __init__(
        self,
        state_dir: Path,
        profile_loader: Callable[[], dict[str, Any]] | None = None,
        profile_saver: Callable[[dict[str, Any]], None] | None = None,
        *,
        embed_client: EmbeddingClient | None = None,
        memos_config: MemosConfig | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._facts_path = state_dir / "facts.json"
        self._fact_ttls_path = state_dir / "fact_ttls.json"
        self._episodes_path = state_dir / "episodes.jsonl"
        self._embeddings_path = state_dir / "embeddings.json"
        self._profile_loader = profile_loader
        self._profile_saver = profile_saver

        # Enhanced features
        self._fts = FTS5Index(state_dir)
        self._embed = embed_client or EmbeddingClient()
        self._memos = MemosClient(memos_config or MemosConfig())

        # Cache for vector embeddings (episode_id → vector). Persisted to
        # ``embeddings.json`` so embeddings survive a process restart (P3-2),
        # avoiding expensive re-computation via the Ollama embed endpoint.
        self._embedding_cache: dict[str, list[float]] = self._load_embeddings()

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
        """Append *episode* to the JSONL episode log and sync to FTS5/MemOS."""
        payload = {
            "id": episode.id,
            "kind": episode.kind,
            "summary": episode.summary,
            "details": episode.details,
            "created_at": episode.created_at,
        }
        atomic_append_jsonl(self._episodes_path, payload)
        # Sync to FTS5 index (best-effort). The JSONL append has already
        # committed the episode, so a failed FTS write must not raise and cause
        # a caller retry that would duplicate the JSONL row — degrade like the
        # MemOS sync below instead.
        try:
            self._fts.index(episode)
        except Exception:  # noqa: BLE001
            logger.exception("FTS5 index failed for episode %s; JSONL already appended", episode.id)
        # Sync to MemOS if enabled (best-effort, non-blocking)
        if self._memos.available:
            try:
                self._memos.ingest(episode)
            except Exception:  # noqa: BLE001
                pass

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

    # ------------------------------------------------------------------
    # Enhanced search: FTS5
    # ------------------------------------------------------------------
    def search_episodes_fts(
        self, query: str, limit: int = 10, kind: str | None = None
    ) -> list[tuple[Episode, float]]:
        """Full-text search via FTS5 (BM25 ranking).

        Returns ``(episode, score)`` tuples, highest score first.
        """
        return self._fts.search(query, limit=limit, kind=kind)

    # ------------------------------------------------------------------
    # Enhanced search: vector / semantic
    # ------------------------------------------------------------------
    def search_episodes_semantic(
        self, query: str, limit: int = 10, kind: str | None = None
    ) -> list[tuple[Episode, float]]:
        """Semantic search via vector embedding cosine similarity.

        Requires Ollama to be running with an embedding model (default:
        ``nomic-embed-text``). If Ollama is unavailable, returns empty list.
        """
        query_emb = self._embed.embed(query)
        if query_emb is None:
            return []
        episodes = self.list_episodes(kind=kind, limit=10000)
        if not episodes:
            return []
        scored: list[tuple[Episode, float]] = []
        for ep in episodes:
            ep_emb = self._get_or_compute_embedding(ep)
            if ep_emb is None:
                continue
            sim = _cosine_similarity(
                {str(i): v for i, v in enumerate(query_emb.vector)},
                {str(i): v for i, v in enumerate(ep_emb)},
            )
            if sim > 0.0:
                scored.append((ep, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def _get_or_compute_embedding(self, episode: Episode) -> list[float] | None:
        """Get cached embedding or compute and cache it.

        Newly computed embeddings are persisted to ``embeddings.json`` so they
        survive process restarts (avoiding re-computation).
        """
        if episode.id in self._embedding_cache:
            return self._embedding_cache[episode.id]
        text = episode.summary
        if episode.details:
            text += " " + json.dumps(episode.details, ensure_ascii=False)
        result = self._embed.embed(text)
        if result is None:
            return None
        self._embedding_cache[episode.id] = result.vector
        self._save_embeddings()
        return result.vector

    def _load_embeddings(self) -> dict[str, list[float]]:
        """Load the persisted embedding cache (best-effort)."""
        data = safe_read_json(self._embeddings_path, default={})
        if not isinstance(data, dict):
            return {}
        cache: dict[str, list[float]] = {}
        for key, value in data.items():
            if isinstance(value, list) and all(isinstance(x, (int, float)) for x in value):
                cache[str(key)] = [float(x) for x in value]
        return cache

    def _save_embeddings(self) -> None:
        """Persist the embedding cache (best-effort; failure is non-fatal)."""
        try:
            atomic_write_json(self._embeddings_path, self._embedding_cache)
        except OSError:
            logger.exception("failed to persist embedding cache")

    # ------------------------------------------------------------------
    # Enhanced search: RRF-4 fusion (substring + TF-IDF + FTS5 + vector)
    # ------------------------------------------------------------------
    def search_episodes_rrf(
        self,
        query: str,
        limit: int = 10,
        kind: str | None = None,
        k: int = 60,
    ) -> list[tuple[Episode, float]]:
        """Hybrid episode search using Reciprocal Rank Fusion (4 signals).

        Fuses four retrieval signals:
          1. Exact substring match (case-insensitive) on summary + details
          2. TF-IDF cosine similarity (semantic-ish keyword overlap)
          3. FTS5 BM25 full-text search (sqlite3)
          4. Vector embedding cosine similarity (Ollama, optional)

        RRF score = sum(1 / (k + rank)) across ranked lists. Signals 4 is
        only included when Ollama is available.
        """
        if not query or not query.strip():
            return []
        episodes = self.list_episodes(kind=kind, limit=10000)
        if not episodes:
            return []
        q_lower = query.lower()

        # Signal 1: exact substring match
        substring_matches: list[tuple[Episode, int]] = []
        for ep in episodes:
            text = ep.summary.lower()
            if ep.details:
                text += " " + json.dumps(ep.details, ensure_ascii=False).lower()
            pos = text.find(q_lower)
            if pos != -1:
                substring_matches.append((ep, pos))
        substring_matches.sort(key=lambda x: x[1])
        sub_ranks: dict[str, int] = {
            ep.id: rank for rank, (ep, _pos) in enumerate(substring_matches)
        }

        # Signal 2: TF-IDF cosine similarity
        tfidf_results = self.search_episodes(query, limit=len(episodes), kind=kind)
        tfidf_ranks: dict[str, int] = {
            ep.id: rank for rank, (ep, _score) in enumerate(tfidf_results)
        }

        # Signal 3: FTS5 BM25
        fts_results = self.search_episodes_fts(query, limit=len(episodes), kind=kind)
        fts_ranks: dict[str, int] = {
            ep.id: rank for rank, (ep, _score) in enumerate(fts_results)
        }

        # Signal 4: vector embedding (optional)
        semantic_ranks: dict[str, int] = {}
        semantic_results = self.search_episodes_semantic(query, limit=len(episodes), kind=kind)
        if semantic_results:
            semantic_ranks = {
                ep.id: rank for rank, (ep, _score) in enumerate(semantic_results)
            }

        # Fuse via RRF
        all_signals = [sub_ranks, tfidf_ranks, fts_ranks]
        if semantic_ranks:
            all_signals.append(semantic_ranks)
        all_ids = set(sub_ranks)
        for ranks in all_signals[1:]:
            all_ids |= set(ranks)
        if not all_ids:
            return []
        id_to_ep: dict[str, Episode] = {ep.id: ep for ep in episodes}
        fused: list[tuple[Episode, float]] = []
        for ep_id in all_ids:
            score = 0.0
            for ranks in all_signals:
                if ep_id in ranks:
                    score += 1.0 / (k + ranks[ep_id])
            found_ep = id_to_ep.get(ep_id)
            if found_ep is not None:
                fused.append((found_ep, score))
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
        """Multi-level compaction: L1 raw → L2 grouped → L3 abstract.

        **L1 (raw)**: Keep the most recent *keep_recent* episodes intact.
        **L2 (grouped)**: Episodes beyond the window are grouped by kind and
        time period (daily), producing per-kind-per-day summary episodes.
        **L3 (abstract)**: If L2 summaries for the same kind exceed a
        threshold, they are further aggregated into abstract skill/pattern
        summaries.

        Returns a dict describing the compaction result:
            {"compacted_kinds": [...], "removed": N, "l2_summaries": M, "l3_summaries": P}

        When *kind* is set, only that kind's episodes are compacted; episodes
        of every other kind are preserved verbatim (they are never dropped).
        """
        # Load ALL episodes (unfiltered) so a kind-scoped compaction does not
        # silently discard other kinds when rewriting the JSONL file.
        all_episodes = self.list_episodes(limit=10**9)
        if kind is not None:
            target = [e for e in all_episodes if e.kind == kind]
            others = [e for e in all_episodes if e.kind != kind]
        else:
            target = all_episodes
            others = []

        if len(target) <= keep_recent:
            return {"compacted_kinds": [], "removed": 0, "l2_summaries": 0, "l3_summaries": 0}

        recent = target[:keep_recent]
        old = target[keep_recent:]

        # --- L2: Group by kind + day ---
        by_kind_day: dict[tuple[str, int], list[Episode]] = {}
        for ep in old:
            day_key = int(ep.created_at // 86400)  # group by day
            key = (ep.kind, day_key)
            by_kind_day.setdefault(key, []).append(ep)

        l2_summaries: list[Episode] = []
        for (ep_kind, day_key), eps in by_kind_day.items():
            timestamps = [e.created_at for e in eps]
            summary = make_episode(
                f"{ep_kind}_l2_summary",
                f"[L2] {len(eps)} {ep_kind} episodes on day {day_key}",
                {
                    "kind": ep_kind,
                    "level": 2,
                    "count": len(eps),
                    "first_at": min(timestamps),
                    "last_at": max(timestamps),
                    "compacted": True,
                },
            )
            l2_summaries.append(summary)

        # --- L3: Aggregate L2 summaries per kind (if > 5 L2 summaries) ---
        l3_summaries: list[Episode] = []
        l2_by_kind: dict[str, list[Episode]] = {}
        for s in l2_summaries:
            kind_base = s.details.get("kind", "")
            l2_by_kind.setdefault(kind_base, []).append(s)

        remaining_l2: list[Episode] = []
        for kind_base, summaries in l2_by_kind.items():
            if len(summaries) > 5:
                timestamps = [s.created_at for s in summaries]
                total_count = sum(s.details.get("count", 0) for s in summaries)
                l3 = make_episode(
                    f"{kind_base}_l3_abstract",
                    f"[L3] {total_count} {kind_base} episodes across {len(summaries)} days",
                    {
                        "kind": kind_base,
                        "level": 3,
                        "count": total_count,
                        "days": len(summaries),
                        "first_at": min(timestamps),
                        "last_at": max(timestamps),
                        "compacted": True,
                    },
                )
                l3_summaries.append(l3)
            else:
                remaining_l2.extend(summaries)

        # --- Rewrite episodes file ---
        # Order: L3 abstracts (oldest) → L2 summaries → recent (newest).
        # Other-kind episodes are appended verbatim (reversed to oldest-first,
        # matching list_episodes' newest-first return order).
        to_write: list[Episode] = []
        to_write.extend(l3_summaries)
        to_write.extend(remaining_l2)
        to_write.extend(reversed(recent))
        to_write.extend(reversed(others))

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

        # Rebuild FTS5 index from the compacted episodes
        self._fts.rebuild(to_write)

        return {
            "compacted_kinds": list(by_kind_day.keys()),
            "removed": len(old),
            "l2_summaries": len(remaining_l2),
            "l3_summaries": len(l3_summaries),
        }

    def archive_episodes(self, older_than_days: float = 30.0) -> int:
        """Move episodes older than *older_than_days* into a cold archive file.

        Unlike :meth:`compact_episodes` (which summarizes old episodes in
        place), archiving *moves* old episodes out of the hot ``episodes.jsonl``
        into ``episodes.archive.jsonl``, keeping the active log small while
        preserving the full record for audit. Returns the number archived.
        """
        cutoff = time.time() - older_than_days * 86400.0
        if not self._episodes_path.exists():
            return 0

        active: list[Episode] = []
        archived: list[Episode] = []
        with self._episodes_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ep = _parse_episode_line(line)
                except (ValueError, KeyError):
                    continue
                (archived if ep.created_at < cutoff else active).append(ep)

        if not archived:
            return 0

        archive_path = self.state_dir / "episodes.archive.jsonl"
        for ep in archived:
            atomic_append_jsonl(
                archive_path,
                {
                    "id": ep.id,
                    "kind": ep.kind,
                    "summary": ep.summary,
                    "details": ep.details,
                    "created_at": ep.created_at,
                },
            )

        # Rewrite the hot file with only the active episodes.
        lines = [
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
            for ep in active
        ]
        self._episodes_path.write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )

        # FTS index must reflect only the active set.
        self._fts.rebuild(active)

        return len(archived)

    # ------------------------------------------------------------------
    # MemOS integration
    # ------------------------------------------------------------------
    def memos_health(self) -> bool:
        """Check if the MemOS local plugin is healthy."""
        return self._memos.health()

    def memos_search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Proxy a search to the MemOS local plugin."""
        return self._memos.search(query, limit=limit)

    def memos_feedback(self, memory_id: str, correction: str) -> bool:
        """Submit a feedback correction to the MemOS plugin."""
        return self._memos.feedback(memory_id, correction)


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


# ============================================================================
# FTS5 full-text search index (sqlite3, zero external deps)
# ============================================================================


class FTS5Index:
    """SQLite FTS5 full-text search index for episode summaries and details.

    Uses Python's built-in ``sqlite3`` module — zero external dependencies.
    The index is stored alongside the episodes JSONL in the state directory.

    Thread safety: each thread gets its own sqlite3 connection (sqlite3
    connections are bound to the thread that created them). Schema creation
    is guarded by a module-level lock so concurrent first-touch on a fresh
    index cannot race. WAL mode allows concurrent readers/writers across
    connections.
    """

    def __init__(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = state_dir / "episodes_fts.db"
        self._local = threading.local()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return the calling thread's dedicated connection, creating it lazily."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=True)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._ensure_tables(conn)
            self._local.conn = conn
        return conn

    def _ensure_tables(self, conn: sqlite3.Connection) -> None:
        # Schema creation is not fully atomic across concurrent connections;
        # guard with a module-level lock (cheap, only taken during first touch).
        with _FTS_SCHEMA_LOCK:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS episodes_fts("
                "  id TEXT PRIMARY KEY,"
                "  kind TEXT,"
                "  summary TEXT,"
                "  details_json TEXT,"
                "  created_at REAL"
                ")"
            )
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts_idx "
                "USING fts5(id, kind, summary, details_json, content='episodes_fts',"
                " content_rowid='rowid')"
            )
            # Triggers to keep FTS index in sync
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS episodes_fts_ai AFTER INSERT ON episodes_fts BEGIN "
                "  INSERT INTO episodes_fts_idx(rowid, id, kind, summary, details_json) "
                "  VALUES (new.rowid, new.id, new.kind, new.summary, new.details_json);"
                "END"
            )
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS episodes_fts_ad AFTER DELETE ON episodes_fts BEGIN "
                "  INSERT INTO episodes_fts_idx(episodes_fts_idx, rowid, id, kind, summary, details_json) "
                "  VALUES('delete', old.rowid, old.id, old.kind, old.summary, old.details_json);"
                "END"
            )
            conn.commit()

    def index(self, episode: Episode) -> None:
        """Insert or replace an episode in the FTS index."""
        conn = self._conn
        conn.execute(
            "INSERT OR REPLACE INTO episodes_fts(id, kind, summary, details_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                episode.id,
                episode.kind,
                episode.summary,
                json.dumps(episode.details, ensure_ascii=False),
                episode.created_at,
            ),
        )
        conn.commit()

    def search(
        self, query: str, limit: int = 20, kind: str | None = None
    ) -> list[tuple[Episode, float]]:
        """Full-text search via FTS5, returning (episode, bm25_score) tuples.

        Results are ranked by BM25 relevance. The raw BM25 score is negated
        and normalized to a 0-1 range so higher = better (consistent with
        other scoring methods).
        """
        if not query.strip():
            return []
        escaped = query.replace('"', '""')
        conditions = ["episodes_fts_idx MATCH ?"]
        params: list[Any] = [f'"{escaped}"']
        sql = (
            "SELECT e.id, e.kind, e.summary, e.details_json, e.created_at, rank "
            "FROM episodes_fts_idx "
            "JOIN episodes_fts e ON episodes_fts_idx.rowid = e.rowid "
        )
        if kind:
            conditions.append("e.kind = ?")
            params.append(kind)
        sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        results: list[tuple[Episode, float]] = []
        if not rows:
            return results
        max_rank = max(abs(row[5]) for row in rows) or 1.0
        for row in rows:
            ep = Episode(
                id=row[0],
                kind=row[1],
                summary=row[2],
                details=json.loads(row[3]) if row[3] else {},
                created_at=row[4],
            )
            # FTS5 rank is negative (more negative = more relevant). Normalize
            # so the best match gets score 1.0 (higher = better, consistent
            # with the TF-IDF / cosine scorers).
            score = abs(row[5]) / max_rank
            results.append((ep, score))
        return results

    def rebuild(self, episodes: list[Episode]) -> None:
        """Rebuild the FTS index from a list of episodes (e.g. after compaction)."""
        conn = self._conn
        conn.execute("DELETE FROM episodes_fts")
        for ep in episodes:
            self.index(ep)

    def close(self) -> None:
        """Close the calling thread's connection (best-effort)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._local.conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass


# ============================================================================
# Vector embedding client (Ollama-compatible, optional)
# ============================================================================


@dataclass
class EmbeddingResult:
    """A single embedding vector with its metadata."""

    vector: list[float]
    model: str = ""
    dimension: int = 0

    def __post_init__(self) -> None:
        self.dimension = len(self.vector)


class EmbeddingClient:
    """HTTP client for Ollama's /api/embed endpoint.

    Uses only stdlib ``urllib`` — zero external dependencies.
    Embedding is optional; if the Ollama server is unavailable, vector-based
    search methods gracefully return empty results.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, text: str) -> EmbeddingResult | None:
        """Get embedding vector for *text* from Ollama. Returns None on failure."""
        import urllib.error
        import urllib.request

        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                emb = data.get("embeddings", [[]])[0]
                return EmbeddingResult(vector=emb, model=self.model)
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError, IndexError):
            return None

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult | None]:
        """Get embeddings for multiple texts. Failed items are None."""
        return [self.embed(t) for t in texts]

    def health(self) -> bool:
        """Check if the Ollama server is reachable."""
        return self.embed("ping") is not None


# ============================================================================
# MemOS local plugin adapter (optional HTTP client)
# ============================================================================


@dataclass
class MemosConfig:
    """Configuration for the MemOS local plugin adapter."""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:18800"
    timeout: float = 10.0


class MemosClient:
    """HTTP client for the MemOS local plugin (Node.js process on :18800).

    This is an optional integration layer. When enabled, episodes are synced
    to MemOS for advanced vector search and memory evolution. When disabled
    (default), the system operates entirely standalone.
    """

    def __init__(self, config: MemosConfig | None = None) -> None:
        self.config = config or MemosConfig()

    @property
    def available(self) -> bool:
        return self.config.enabled

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
        import urllib.error
        import urllib.request

        url = f"{self.config.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                loaded = json.loads(resp.read().decode("utf-8"))
                return loaded if isinstance(loaded, dict) else None
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return None

    def health(self) -> bool:
        result = self._request("GET", "/health")
        return result is not None

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        result = self._request("GET", f"/api/search?q={query}&limit={limit}")
        if result and isinstance(result, dict):
            results = result.get("results", [])
            return results if isinstance(results, list) else []
        return []

    def ingest(self, episode: Episode) -> bool:
        payload = {
            "id": episode.id,
            "kind": episode.kind,
            "summary": episode.summary,
            "details": episode.details,
            "created_at": episode.created_at,
        }
        result = self._request("POST", "/api/memories", payload)
        return result is not None

    def feedback(self, memory_id: str, correction: str) -> bool:
        result = self._request("POST", f"/api/memories/{memory_id}/feedback", {"correction": correction})
        return result is not None
