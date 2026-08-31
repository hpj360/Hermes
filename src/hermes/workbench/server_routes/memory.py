"""Memory routes: facts / episodes / 检索三通道 / profile / MemOS.

从 server.py 拆出的路由域 mixin。
"""
from __future__ import annotations

from hermes.workbench.server_routes.base import RouteBase

from hermes.workbench.errors import ValidationError, NotFoundError


class MemoryRoutes(RouteBase):
    def h_get_facts(self) -> None:
        from hermes.workbench.cli import _make_memory

        facts = _make_memory().list_facts()
        self._send_json(200, {"facts": facts})

    def h_post_facts(self) -> None:
        from hermes.workbench.cli import _make_memory

        body = self._read_json_body()
        if not isinstance(body, dict) or "key" not in body or "value" not in body:
            raise ValidationError("body must contain 'key' and 'value'")
        _make_memory().remember_fact(body["key"], body["value"])
        self._send_json(201, {"key": body["key"], "value": body["value"]})

    def h_get_fact(self, key: str) -> None:
        from hermes.workbench.cli import _make_memory

        fact = _make_memory().get_fact(key)
        if fact is None:
            raise NotFoundError(f"fact not found: {key}")
        self._send_json(200, fact)

    def h_delete_fact(self, key: str) -> None:
        from hermes.workbench.cli import _make_memory

        if not _make_memory().forget_fact(key):
            raise NotFoundError(f"fact not found: {key}")
        self._send_no_content()

    def h_get_episodes(self) -> None:
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        episodes = _make_memory().list_episodes(kind=params.get("kind"))
        self._send_json(200, {"episodes": [e.__dict__ for e in episodes]})

    def h_get_memory_search(self) -> None:
        """Search episodes by keyword (TF-IDF cosine similarity).

        Query params: ?q=keyword&limit=10&kind=some_kind
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "10"))
        kind = params.get("kind")
        results = _make_memory().search_episodes(query=q, limit=limit, kind=kind)
        self._send_json(
            200,
            {
                "query": q,
                "results": [
                    {"episode": ep.__dict__, "score": round(score, 4)}
                    for ep, score in results
                ],
            },
        )

    def h_get_memory_search_rrf(self) -> None:
        """Hybrid episode search via Reciprocal Rank Fusion.

        Fuses exact-substring and TF-IDF signals. Query params same as
        /memory/search, plus optional ``k`` (RRF constant, default 60).
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "10"))
        kind = params.get("kind")
        k = int(params.get("k", "60"))
        results = _make_memory().search_episodes_rrf(
            query=q, limit=limit, kind=kind, k=k
        )
        self._send_json(
            200,
            {
                "query": q,
                "method": "rrf",
                "results": [
                    {"episode": ep.__dict__, "score": round(score, 6)}
                    for ep, score in results
                ],
            },
        )

    def h_get_memory_search_fts(self) -> None:
        """Full-text search via FTS5 (BM25 ranking).

        Query params: ?q=keyword&limit=10&kind=some_kind
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "10"))
        kind = params.get("kind")
        results = _make_memory().search_episodes_fts(query=q, limit=limit, kind=kind)
        self._send_json(
            200,
            {
                "query": q,
                "method": "fts5",
                "results": [
                    {"episode": ep.__dict__, "score": round(score, 4)}
                    for ep, score in results
                ],
            },
        )

    def h_get_memory_search_semantic(self) -> None:
        """Semantic search via vector embedding (Ollama).

        Query params: ?q=keyword&limit=10&kind=some_kind
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "10"))
        kind = params.get("kind")
        results = _make_memory().search_episodes_semantic(query=q, limit=limit, kind=kind)
        self._send_json(
            200,
            {
                "query": q,
                "method": "semantic",
                "results": [
                    {"episode": ep.__dict__, "score": round(score, 4)}
                    for ep, score in results
                ],
            },
        )

    def h_post_memory_cleanup(self) -> None:
        """Purge all expired facts (TTL elapsed). Returns the count removed."""
        from hermes.workbench.cli import _make_memory

        removed = _make_memory().cleanup_expired_facts()
        self._send_json(200, {"removed": removed})

    def h_post_memory_learn(self) -> None:
        """Learn profile insights from recent episodes.

        Body (optional): {"recent_count": 200, "top_n": 5}
        """
        from hermes.workbench.cli import _make_memory

        body = self._read_json_body()
        recent_count = int(body.get("recent_count", 200))
        top_n = int(body.get("top_n", 5))
        insights = _make_memory().learn_profile_from_episodes(
            recent_count=recent_count, top_n=top_n
        )
        self._send_json(200, {"insights": insights})

    def h_post_memory_compact(self) -> None:
        """Compact old episodes into per-kind summary episodes.

        Body (optional): {"keep_recent": 200, "kind": null}
        """
        from hermes.workbench.cli import _make_memory

        body = self._read_json_body()
        keep_recent = int(body.get("keep_recent", 200))
        kind = body.get("kind")
        result = _make_memory().compact_episodes(keep_recent=keep_recent, kind=kind)
        self._send_json(200, result)

    def h_get_profile(self) -> None:
        from hermes.workbench.cli import _make_memory

        profile = _make_memory().get_user_profile()
        self._send_json(200, profile)

    def h_get_memos_health(self) -> None:
        """Check MemOS local plugin health."""
        from hermes.workbench.cli import _make_memory

        mem = _make_memory()
        ok = mem.memos_health()
        self._send_json(200, {"memos": {"healthy": ok, "enabled": mem._memos.available}})

    def h_get_memos_search(self) -> None:
        """Proxy search to MemOS local plugin.

        Query params: ?q=keyword&limit=10
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "10"))
        results = _make_memory().memos_search(query=q, limit=limit)
        self._send_json(200, {"query": q, "source": "memos", "results": results})

    def h_post_memos_feedback(self) -> None:
        """Submit feedback correction to MemOS plugin."""
        from hermes.workbench.cli import _make_memory

        body = self._read_json_body()
        memory_id = body.get("memory_id", "")
        correction = body.get("correction", "")
        if not memory_id or not correction:
            raise ValidationError("memory_id and correction are required")
        ok = _make_memory().memos_feedback(memory_id, correction)
        self._send_json(200 if ok else 503, {"success": ok})

