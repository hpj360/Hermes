"""Tests for workbench.server module.

Uses http.client against a real ThreadingHTTPServer on an ephemeral port.
"""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from hermes.workbench.server import make_server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    base = tmp_path / "skills"
    for name in ("alpha", "beta"):
        s = base / name
        s.mkdir(parents=True)
        (s / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} skill\n---\n# {name}\nHello {name}.\n",
            encoding="utf-8",
        )
    return base


@pytest.fixture
def patched_services(monkeypatch, skills_dir, tmp_path):
    """Patch cli factories to use tmp-based isolated services."""
    from hermes.workbench import cli as cli_mod
    from hermes.workbench.memory import MemoryService
    from hermes.workbench.skill_runner import SkillRunner

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("hermes.workbench.services._state_dir", lambda: state)
    runner = SkillRunner(base_dir=skills_dir)
    memory = MemoryService(state_dir=state)
    store = cli_mod.TaskStore(state_dir=state)
    registry = cli_mod.TaskRegistry()
    scheduler = cli_mod.TaskScheduler(
        store=store, registry=registry, runner=runner, memory=memory
    )

    monkeypatch.setattr(cli_mod, "_make_runner", lambda: runner)
    monkeypatch.setattr(cli_mod, "_make_memory", lambda: memory)
    monkeypatch.setattr(cli_mod, "_make_store", lambda: store)
    monkeypatch.setattr(cli_mod, "_make_registry", lambda: registry)
    monkeypatch.setattr(cli_mod, "_make_scheduler", lambda: scheduler)

    # Phase 3 scheduler center: build a fresh center pointed at tmp state so
    # the new /jobs, /projects, /triggers, /sync, /health routes are isolated.
    monkeypatch.setattr("hermes.workbench.services._state_dir", lambda: state)
    cli_mod._reset_scheduler_center()
    center = cli_mod._SchedulerCenter()
    monkeypatch.setattr(cli_mod, "_make_scheduler_center", lambda: center)
    return {
        "store": store,
        "registry": registry,
        "scheduler": scheduler,
        "center": center,
    }


@pytest.fixture
def server(patched_services):
    srv = make_server(host="127.0.0.1", port=0)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=2)


@pytest.fixture
def client(server):
    host, port = server.server_address[:2]

    def request(
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        h: dict[str, str] = {}
        if body is not None:
            h["Content-Type"] = "application/json"
        if headers:
            h.update(headers)
        if body is not None:
            conn.request(method, path, body=json.dumps(body), headers=h)
        else:
            conn.request(method, path, headers=h)
        resp = conn.getresponse()
        resp.text = resp.read().decode("utf-8")  # type: ignore[attr-defined]
        conn.close()
        return resp

    return request


def _json(resp):
    return json.loads(resp.text)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def test_health(client):
    resp = client("GET", "/health")
    assert resp.status == 200
    assert _json(resp)["status"] == "ok"


def test_metrics_prometheus_format(client):
    """GET /metrics should return Prometheus text exposition."""
    resp = client("GET", "/metrics")
    assert resp.status == 200
    assert resp.getheader("Content-Type", "").startswith("text/plain")
    assert "hermes_jobs_total" in resp.text
    assert "hermes_jobs_queue_depth" in resp.text
    assert "hermes_jobs_by_status" in resp.text
    # All three metrics are gauges.
    assert resp.text.count("# TYPE") >= 3


def test_kb_search_not_configured(client, monkeypatch):
    """GET /kb/search should degrade to 503 when hermes-kb is not configured."""
    class FakeSettings:
        hermes_kb_base_url = ""
        openclaw_gateway_token = None

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    resp = client("GET", "/kb/search?q=hello")
    assert resp.status == 503
    body = _json(resp)
    assert body["results"] == []


def test_kb_search_missing_query(client):
    """GET /kb/search without ?q should be a validation error (400)."""
    resp = client("GET", "/kb/search")
    assert resp.status == 400


def test_unknown_route_404(client):
    resp = client("GET", "/nonexistent")
    assert resp.status == 404


def test_method_not_allowed(client):
    resp = client("PUT", "/skills")
    assert resp.status == 405


# ---------------------------------------------------------------------------
# skills
# ---------------------------------------------------------------------------


def test_skills_list(client):
    resp = client("GET", "/skills")
    assert resp.status == 200
    names = [s["name"] for s in _json(resp)["skills"]]
    assert "alpha" in names


def test_skill_detail(client):
    resp = client("GET", "/skills/alpha")
    assert resp.status == 200
    assert _json(resp)["name"] == "alpha"


def test_skill_detail_missing(client):
    resp = client("GET", "/skills/nonexistent")
    assert resp.status == 404


# ---------------------------------------------------------------------------
# memory facts
# ---------------------------------------------------------------------------


def test_facts_empty(client):
    resp = client("GET", "/memory/facts")
    assert resp.status == 200
    assert _json(resp)["facts"] == []


def test_facts_create_and_get(client):
    resp = client("POST", "/memory/facts", body={"key": "city", "value": "Shanghai"})
    assert resp.status == 201
    resp = client("GET", "/memory/facts/city")
    assert resp.status == 200
    assert _json(resp)["value"] == "Shanghai"


def test_facts_get_missing(client):
    resp = client("GET", "/memory/facts/nonexistent")
    assert resp.status == 404


def test_facts_delete(client):
    client("POST", "/memory/facts", body={"key": "temp", "value": "x"})
    resp = client("DELETE", "/memory/facts/temp")
    assert resp.status == 204
    assert client("GET", "/memory/facts/temp").status == 404


def test_facts_delete_missing(client):
    resp = client("DELETE", "/memory/facts/nonexistent")
    assert resp.status == 404


def test_facts_create_missing_key(client):
    resp = client("POST", "/memory/facts", body={"value": "x"})
    assert resp.status == 400


# ---------------------------------------------------------------------------
# memory episodes + profile
# ---------------------------------------------------------------------------


def test_episodes_empty(client):
    resp = client("GET", "/memory/episodes")
    assert resp.status == 200
    assert _json(resp)["episodes"] == []


def test_profile(client):
    resp = client("GET", "/memory/profile")
    assert resp.status == 200
    assert "version" in _json(resp)


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


def test_tasks_create_and_run(client):
    resp = client("POST", "/tasks", body={"plan": [{"skill": "alpha"}], "run": True})
    assert resp.status == 200
    data = _json(resp)
    assert "task_id" in data
    assert data["status"] in ("COMPLETED", "FAILED")


def test_tasks_list_empty(client):
    resp = client("GET", "/tasks")
    assert resp.status == 200
    assert _json(resp)["tasks"] == []


def test_tasks_list_after_create(client):
    client("POST", "/tasks", body={"plan": [{"skill": "alpha"}], "run": False})
    resp = client("GET", "/tasks")
    assert resp.status == 200
    assert len(_json(resp)["tasks"]) == 1


def test_task_detail(client):
    create = client("POST", "/tasks", body={"plan": [{"skill": "alpha"}], "run": False})
    task_id = _json(create)["task_id"]
    resp = client("GET", f"/tasks/{task_id}")
    assert resp.status == 200
    assert _json(resp)["task_id"] == task_id


def test_task_detail_missing(client):
    resp = client("GET", "/tasks/nonexistent")
    assert resp.status == 404


def test_task_cancel(client):
    create = client("POST", "/tasks", body={"plan": [{"skill": "alpha"}], "run": False})
    task_id = _json(create)["task_id"]
    resp = client("POST", f"/tasks/{task_id}/cancel")
    assert resp.status == 200
    assert _json(resp)["status"] == "CANCELLED"


def test_task_cancel_missing(client):
    resp = client("POST", "/tasks/nonexistent/cancel")
    assert resp.status == 404


def test_task_create_missing_plan(client):
    resp = client("POST", "/tasks", body={"mode": "oneshot"})
    assert resp.status == 400


# ---------------------------------------------------------------------------
# github sync (mocked)
# ---------------------------------------------------------------------------


def test_github_sync_no_repo(client):
    resp = client("GET", "/github/sync")
    assert resp.status == 400


def test_github_sync_no_token(client, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    resp = client("GET", "/github/sync?repo=owner/repo")
    assert resp.status == 400


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_auth_disabled_by_default(client):
    """When OPENCLAW_GATEWAY_TOKEN is unset, all routes are open."""
    resp = client("GET", "/skills")
    assert resp.status == 200


def test_auth_health_is_public(client, monkeypatch):
    """The /health endpoint should always be accessible."""

    class FakeSettings:
        openclaw_gateway_token = "secret"

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    resp = client("GET", "/health")
    assert resp.status == 200


def test_auth_required_when_token_set(client, monkeypatch):
    """When token is set, protected routes require Bearer auth."""

    class FakeSettings:
        openclaw_gateway_token = "secret-token"

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    resp = client("GET", "/skills")
    assert resp.status == 401


def test_auth_valid_bearer_token_passes(client, monkeypatch):
    """Correct Bearer token should allow access."""

    class FakeSettings:
        openclaw_gateway_token = "secret-token"

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    resp = client("GET", "/skills", headers={"Authorization": "Bearer secret-token"})
    assert resp.status == 200


def test_auth_invalid_bearer_token_rejected(client, monkeypatch):
    """Wrong Bearer token should be rejected."""

    class FakeSettings:
        openclaw_gateway_token = "secret-token"

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    resp = client("GET", "/skills", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status == 401


def test_auth_hermes_api_token_priority(client, monkeypatch):
    """HERMES_API_TOKEN takes priority over the legacy gateway token."""
    from hermes.workbench.server import DashboardHandler

    class _FakeHandler:
        def __init__(self) -> None:
            self.headers = {"Authorization": "Bearer hermes-token"}

    class FakeSettings:
        hermes_api_token = "hermes-token"
        openclaw_gateway_token = "legacy-token"

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    assert DashboardHandler._check_auth(_FakeHandler()) is True


def test_auth_hermes_api_token_rejects_legacy(client, monkeypatch):
    """Legacy token no longer authenticates when HERMES_API_TOKEN is set."""
    from hermes.workbench.server import DashboardHandler

    class _FakeHandler:
        def __init__(self) -> None:
            self.headers = {"Authorization": "Bearer legacy-token"}

    class FakeSettings:
        hermes_api_token = "hermes-token"
        openclaw_gateway_token = "legacy-token"

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    assert DashboardHandler._check_auth(_FakeHandler()) is False


def test_make_server_refuses_non_loopback_without_token(monkeypatch):
    """U2: non-loopback bind without token is refused (unless --insecure)."""
    from hermes.workbench.server import make_server

    class FakeSettings:
        hermes_api_token = None
        openclaw_gateway_token = None

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    with pytest.raises(ValueError, match="HERMES_API_TOKEN"):
        make_server("0.0.0.0", 8123)


def test_make_server_allows_non_loopback_insecure(monkeypatch):
    """U2: --insecure explicitly opts out of the loopback guard."""
    from hermes.workbench.server import make_server

    class FakeSettings:
        hermes_api_token = None
        openclaw_gateway_token = None

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    srv = make_server("0.0.0.0", 0, insecure=True)
    srv.server_close()


def test_make_server_loopback_without_token_allowed(monkeypatch):
    """U2: loopback bind without token stays allowed (dev mode)."""
    from hermes.workbench.server import make_server

    class FakeSettings:
        hermes_api_token = None
        openclaw_gateway_token = None

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    srv = make_server("127.0.0.1", 0)
    srv.server_close()


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def test_cors_headers_on_json_response(client):
    """JSON responses should include CORS headers."""
    resp = client("GET", "/health")
    assert resp.getheader("Access-Control-Allow-Origin") == "*"


def test_cors_preflight_options(client):
    """OPTIONS preflight should return 204 with CORS headers."""
    resp = client("OPTIONS", "/skills")
    assert resp.status == 204
    assert resp.getheader("Access-Control-Allow-Origin") == "*"
    assert "GET" in (resp.getheader("Access-Control-Allow-Methods") or "")


# ---------------------------------------------------------------------------
# Memory search API
# ---------------------------------------------------------------------------


def test_memory_search_no_query_returns_400(client):
    resp = client("GET", "/memory/search")
    assert resp.status == 400


def test_memory_search_returns_results(client):
    """Search should return matching episodes."""
    # Record an episode first
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode

    mem = _make_memory()
    mem.record_episode(make_episode("note", "deploy python service"))
    mem.record_episode(make_episode("note", "fix javascript bug"))

    resp = client("GET", "/memory/search?q=python")
    assert resp.status == 200
    data = _json(resp)
    assert data["query"] == "python"
    assert len(data["results"]) >= 1
    assert all("episode" in r and "score" in r for r in data["results"])


def test_memory_search_empty_results(client):
    resp = client("GET", "/memory/search?q=nonexistenttopic12345")
    assert resp.status == 200
    assert _json(resp)["results"] == []


def test_memory_search_rrf_returns_results(client):
    """Hybrid RRF search should return fused results."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode

    mem = _make_memory()
    mem.record_episode(make_episode("note", "deploy python service"))
    mem.record_episode(make_episode("note", "fix javascript bug"))

    resp = client("GET", "/memory/search/rrf?q=python")
    assert resp.status == 200
    data = _json(resp)
    assert data["method"] == "rrf"
    assert len(data["results"]) >= 1
    assert all("episode" in r and "score" in r for r in data["results"])


def test_memory_search_rrf_no_query_returns_400(client):
    resp = client("GET", "/memory/search/rrf")
    assert resp.status == 400


def test_memory_search_fts_returns_results(client):
    """FTS5 search should return BM25-ranked episodes."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode

    mem = _make_memory()
    mem.record_episode(make_episode("note", "deploy python service"))
    mem.record_episode(make_episode("note", "fix javascript bug"))

    resp = client("GET", "/memory/search/fts?q=python")
    assert resp.status == 200
    data = _json(resp)
    assert data["method"] == "fts5"
    assert len(data["results"]) >= 1


def test_memory_search_fts_no_query_returns_400(client):
    resp = client("GET", "/memory/search/fts")
    assert resp.status == 400


def test_memory_search_semantic_no_ollama_returns_empty(client):
    """Semantic search degrades to empty results when Ollama is unavailable."""
    resp = client("GET", "/memory/search/semantic?q=python")
    assert resp.status == 200
    data = _json(resp)
    assert data["method"] == "semantic"
    assert data["results"] == []


def test_memory_search_semantic_no_query_returns_400(client):
    resp = client("GET", "/memory/search/semantic")
    assert resp.status == 400


def test_memory_cleanup_returns_count(client):
    """Cleanup should return the number of expired facts removed."""
    resp = client("POST", "/memory/cleanup")
    assert resp.status == 200
    data = _json(resp)
    assert "removed" in data
    assert isinstance(data["removed"], int)


def test_memory_learn_returns_insights(client):
    """Learn endpoint should return profile insights."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode

    mem = _make_memory()
    mem.record_episode(make_episode("loop", "ran a python task", {"skill": "weather"}))
    mem.record_episode(make_episode("loop", "ran another task", {"skill": "weather"}))

    resp = client("POST", "/memory/learn", body={"recent_count": 100, "top_n": 5})
    assert resp.status == 200
    data = _json(resp)
    assert "insights" in data
    assert data["insights"]["episode_count"] >= 2


def test_memory_compact_returns_summary(client):
    """Compact endpoint should return compaction stats."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode

    mem = _make_memory()
    for i in range(10):
        mem.record_episode(make_episode("loop", f"old ep {i}", {"i": i}))

    resp = client("POST", "/memory/compact", body={"keep_recent": 4})
    assert resp.status == 200
    data = _json(resp)
    assert "removed" in data
    assert data["removed"] >= 1


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------


def test_sse_stream_returns_event_stream(server):
    """SSE endpoint should return text/event-stream content type."""
    host, port = server.server_address[:2]
    conn = http.client.HTTPConnection(host, port, timeout=3)
    conn.request("GET", "/stream/episodes")
    resp = conn.getresponse()
    assert resp.status == 200
    assert "text/event-stream" in (resp.getheader("Content-Type") or "")
    # Read a small chunk to verify data is flowing
    chunk = resp.read(256)
    assert len(chunk) > 0
    conn.close()


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------


def test_root_serves_html_dashboard(client):
    resp = client("GET", "/")
    assert resp.status == 200
    assert "text/html" in (resp.getheader("Content-Type") or "")
    body = resp.text
    assert "<html" in body.lower()
    assert "Hermes Workbench" in body
    # Should reference the dashboard JSON endpoint
    assert "/dashboard" in body


def test_dashboard_html_alias(client):
    """/dashboard.html should serve the same HTML as /."""
    resp = client("GET", "/dashboard.html")
    assert resp.status == 200
    assert "text/html" in (resp.getheader("Content-Type") or "")
    assert "Hermes Workbench" in resp.text


def test_dashboard_json_aggregates_state(client, patched_services):
    """/dashboard should return tasks/episodes/facts/skills/traces aggregates."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode

    # Seed some memory state
    mem = _make_memory()
    mem.remember_fact("env", "test")
    mem.record_episode(make_episode("note", "something happened"))

    resp = client("GET", "/dashboard")
    assert resp.status == 200
    data = _json(resp)
    assert "tasks" in data
    assert "episodes" in data
    assert "facts" in data
    assert "skills" in data
    assert "traces" in data
    assert "totals" in data
    assert data["totals"]["facts"] >= 1
    assert data["totals"]["episodes"] >= 1
    # Fact we just stored should appear
    fact_keys = [f["key"] for f in data["facts"]]
    assert "env" in fact_keys


def test_dashboard_with_trace_groups_episodes(patched_services, client):
    """/dashboard should group episodes by trace_id in the traces list."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.tracing import Tracer

    mem = _make_memory()
    tracer = Tracer(mem)
    with tracer.span("trace-xyz"):
        tracer.record_event("planner", "plan")
        tracer.record_event("generator", "exec")
        tracer.record_event("evaluator", "eval")

    resp = client("GET", "/dashboard")
    assert resp.status == 200
    data = _json(resp)
    trace_ids = [t["trace_id"] for t in data["traces"]]
    assert "trace-xyz" in trace_ids
    # Find our trace
    our_trace = next(t for t in data["traces"] if t["trace_id"] == "trace-xyz")
    assert our_trace["count"] == 3
    assert "planner" in our_trace["kinds"]
    assert "generator" in our_trace["kinds"]
    assert "evaluator" in our_trace["kinds"]


def test_dashboard_query_limits_respected(patched_services, client):
    """/dashboard should respect task_limit/episode_limit/fact_limit params."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode

    mem = _make_memory()
    for i in range(10):
        mem.remember_fact(f"k{i}", i)
        mem.record_episode(make_episode("note", f"ep{i}"))

    resp = client("GET", "/dashboard?fact_limit=3&episode_limit=5")
    assert resp.status == 200
    data = _json(resp)
    assert len(data["facts"]) == 3
    assert len(data["episodes"]) == 5


# ---------------------------------------------------------------------------
# traces
# ---------------------------------------------------------------------------


def test_get_trace_returns_chronological_episodes(patched_services, client):
    """GET /traces/{id} should return episodes in chronological order."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.tracing import Tracer

    mem = _make_memory()
    tracer = Tracer(mem)
    with tracer.span("tr-1"):
        tracer.record_event("planner", "first")
        tracer.record_event("generator", "second")
        tracer.record_event("evaluator", "third")

    resp = client("GET", "/traces/tr-1")
    assert resp.status == 200
    data = _json(resp)
    assert data["trace_id"] == "tr-1"
    assert data["count"] == 3
    summaries = [e["summary"] for e in data["episodes"]]
    assert summaries == ["first", "second", "third"]


def test_get_trace_returns_empty_for_unknown_id(patched_services, client):
    resp = client("GET", "/traces/nonexistent")
    assert resp.status == 200
    data = _json(resp)
    assert data["count"] == 0
    assert data["episodes"] == []


def test_get_trace_ignores_untraced_episodes(patched_services, client):
    """Episodes recorded without a trace_id should not appear in trace queries."""
    from hermes.workbench.cli import _make_memory
    from hermes.workbench.memory import make_episode
    from hermes.workbench.tracing import Tracer

    mem = _make_memory()
    mem.record_episode(make_episode("k", "no-trace"))
    tracer = Tracer(mem)
    with tracer.span("real"):
        tracer.record_event("k", "with-trace")

    resp = client("GET", "/traces/real")
    assert resp.status == 200
    data = _json(resp)
    assert data["count"] == 1
    assert data["episodes"][0]["summary"] == "with-trace"


# ---------------------------------------------------------------------------
# Phase 3: health (scheduler extension)
# ---------------------------------------------------------------------------


def test_health_includes_scheduler(patched_services, client):
    """AC-20: /health reports scheduler queue depth + job counts."""
    resp = client("GET", "/health")
    assert resp.status == 200
    data = _json(resp)
    assert data["status"] == "ok"
    assert "scheduler" in data["services"]
    assert data["scheduler"]["queue_depth"] == 0
    assert data["scheduler"]["jobs_total"] == 0
    assert data["scheduler"]["jobs_active"] == 0


# ---------------------------------------------------------------------------
# Phase 3: jobs
# ---------------------------------------------------------------------------


def test_jobs_submit_and_list(patched_services, client):
    """AC-20: POST /jobs creates a QUEUED job; GET /jobs lists it."""
    resp = client("POST", "/jobs", body={"plan": [{"skill": "alpha"}]})
    assert resp.status == 201
    job = _json(resp)
    assert job["status"] == "QUEUED"
    assert job["target_project"] == "default"
    job_id = job["job_id"]

    resp = client("GET", "/jobs")
    assert resp.status == 200
    jobs = _json(resp)["jobs"]
    assert any(j["job_id"] == job_id for j in jobs)


def test_jobs_submit_validates_plan(patched_services, client):
    """AC-20: POST /jobs without plan returns 400."""
    resp = client("POST", "/jobs", body={})
    assert resp.status == 400


def test_jobs_show(patched_services, client):
    """AC-20: GET /jobs/{id} returns the job detail."""
    resp = client("POST", "/jobs", body={"plan": [{"skill": "alpha"}]})
    job_id = _json(resp)["job_id"]
    resp = client("GET", f"/jobs/{job_id}")
    assert resp.status == 200
    assert _json(resp)["job_id"] == job_id


def test_jobs_show_missing_404(patched_services, client):
    resp = client("GET", "/jobs/nonexistent")
    assert resp.status == 404


def test_jobs_cancel(patched_services, client):
    """AC-20: POST /jobs/{id}/cancel marks the job CANCELLED."""
    resp = client("POST", "/jobs", body={"plan": [{"skill": "alpha"}]})
    job_id = _json(resp)["job_id"]
    resp = client("POST", f"/jobs/{job_id}/cancel")
    assert resp.status == 200
    assert _json(resp)["status"] == "CANCELLED"


def test_jobs_retry_requires_terminal(patched_services, client):
    """AC-20: retrying a non-terminal job returns 400."""
    resp = client("POST", "/jobs", body={"plan": [{"skill": "alpha"}]})
    job_id = _json(resp)["job_id"]
    resp = client("POST", f"/jobs/{job_id}/retry")
    assert resp.status == 400


def test_jobs_retry_after_cancel(patched_services, client):
    """AC-20: retrying a terminal job requeues it as QUEUED."""
    resp = client("POST", "/jobs", body={"plan": [{"skill": "alpha"}]})
    job_id = _json(resp)["job_id"]
    client("POST", f"/jobs/{job_id}/cancel")
    resp = client("POST", f"/jobs/{job_id}/retry")
    assert resp.status == 200
    assert _json(resp)["status"] == "QUEUED"


def test_jobs_metrics(patched_services, client):
    """AC-21: GET /jobs/metrics returns aggregated counters."""
    client("POST", "/jobs", body={"plan": [{"skill": "alpha"}]})
    resp = client("GET", "/jobs/metrics")
    assert resp.status == 200
    metrics = _json(resp)
    assert metrics["total"] >= 1
    assert "success_rate" in metrics
    assert "p95_duration_ms" in metrics


def test_jobs_list_filter_by_status(patched_services, client):
    """AC-20: GET /jobs?status=QUEUED filters by status."""
    client("POST", "/jobs", body={"plan": [{"skill": "alpha"}]})
    resp = client("GET", "/jobs?status=QUEUED")
    assert resp.status == 200
    jobs = _json(resp)["jobs"]
    assert all(j["status"] == "QUEUED" for j in jobs)


# ---------------------------------------------------------------------------
# Phase 3: projects
# ---------------------------------------------------------------------------


def test_projects_list_has_default(patched_services, client):
    """AC-22: GET /projects always includes the default project."""
    resp = client("GET", "/projects")
    assert resp.status == 200
    data = _json(resp)
    ids = [p["id"] for p in data["projects"]]
    assert "default" in ids
    assert data["total"] >= 1


def test_projects_add_and_show(patched_services, client, tmp_path):
    """AC-22: POST /projects creates a project; GET /projects/{id} shows it."""
    proj_dir = tmp_path / "proj-state"
    proj_dir.mkdir()
    resp = client(
        "POST",
        "/projects",
        body={
            "name": "TestProj",
            "type": "local",
            "state_dir": str(proj_dir),
            "max_concurrent": 2,
        },
    )
    assert resp.status == 201
    conn = _json(resp)
    assert conn["name"] == "TestProj"
    assert conn["max_concurrent"] == 2
    proj_id = conn["id"]

    resp = client("GET", f"/projects/{proj_id}")
    assert resp.status == 200
    assert _json(resp)["id"] == proj_id


def test_projects_add_validates(patched_services, client):
    """AC-22: POST /projects missing required fields returns 400."""
    resp = client("POST", "/projects", body={"name": "x"})
    assert resp.status == 400


# ---------------------------------------------------------------------------
# loop trajectory API (ADR-0017 / ADR-0020: trajectory view backend)
# ---------------------------------------------------------------------------


_TRAJECTORY_FIXTURE = [
    {
        "seq": 1,
        "time": "2026-08-15T10:00:00",
        "type": "dispatch/request",
        "data": {
            "role": "builder",
            "agent_file": "skills/builder.md",
            "round_num": 1,
            "payload": {"task": "fix bug"},
        },
    },
    {
        "seq": 2,
        "time": "2026-08-15T10:00:05",
        "type": "dispatch/result",
        "data": {
            "request_seq": 1,
            "role": "builder",
            "status": "completed",
            "tokens_used": 1500,
        },
    },
]


@pytest.fixture
def trajectory_loop(patched_services, monkeypatch, tmp_path):
    """Create a tmp .loops/<name>/trajectory.jsonl and point loops_dir at it."""
    loops_root = tmp_path / ".loops"
    loop_dir = loops_root / "demo-loop"
    loop_dir.mkdir(parents=True)
    import json as _json

    lines = [_json.dumps(ev, ensure_ascii=False) for ev in _TRAJECTORY_FIXTURE]
    (loop_dir / "trajectory.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr("hermes.loop.loops_dir", lambda: loops_root)
    return loop_dir


def test_loops_list_empty(patched_services, client, monkeypatch, tmp_path):
    """GET /loops returns empty list when no loops exist."""
    monkeypatch.setattr("hermes.loop.loops_dir", lambda: tmp_path / ".loops")
    resp = client("GET", "/loops")
    assert resp.status == 200
    assert _json(resp) == {"loops": []}


def test_loops_list_with_trajectory(trajectory_loop, client):
    """GET /loops returns loops that have a trajectory.jsonl."""
    resp = client("GET", "/loops")
    assert resp.status == 200
    data = _json(resp)
    assert "demo-loop" in data["loops"]


def test_loop_trajectory_returns_events(trajectory_loop, client):
    """GET /loops/<name>/trajectory returns the event list."""
    resp = client("GET", "/loops/demo-loop/trajectory")
    assert resp.status == 200
    events = _json(resp)["events"]
    assert len(events) == 2
    assert events[0]["type"] == "dispatch/request"
    assert events[1]["type"] == "dispatch/result"


def test_loop_trajectory_missing_loop_404(trajectory_loop, client):
    """GET /loops/<unknown>/trajectory returns 404."""
    resp = client("GET", "/loops/no-such-loop/trajectory")
    assert resp.status == 404


def test_loop_trajectory_verify(trajectory_loop, client):
    """GET /loops/<name>/trajectory/verify returns audit result."""
    resp = client("GET", "/loops/demo-loop/trajectory/verify")
    assert resp.status == 200
    result = _json(resp)
    assert result["ok"] is True
    assert result["events"] == 2
    assert result["requests"] == 1
    assert result["results"] == 1


def test_projects_ping_local(patched_services, client, tmp_path):
    """AC-22: POST /projects/{id}/ping reports reachable for a local project."""
    proj_dir = tmp_path / "ping-state"
    proj_dir.mkdir()
    resp = client(
        "POST",
        "/projects",
        body={"name": "Pingable", "type": "local", "state_dir": str(proj_dir)},
    )
    proj_id = _json(resp)["id"]
    resp = client("POST", f"/projects/{proj_id}/ping")
    assert resp.status == 200
    assert _json(resp)["reachable"] is True


def test_projects_delete(patched_services, client, tmp_path):
    """AC-22: DELETE /projects/{id} removes a non-default project."""
    proj_dir = tmp_path / "del-state"
    proj_dir.mkdir()
    resp = client(
        "POST",
        "/projects",
        body={"name": "Deletable", "type": "local", "state_dir": str(proj_dir)},
    )
    proj_id = _json(resp)["id"]
    resp = client("DELETE", f"/projects/{proj_id}")
    assert resp.status == 204
    # Subsequent get returns 404.
    assert client("GET", f"/projects/{proj_id}").status == 404


def test_projects_show_missing_404(patched_services, client):
    resp = client("GET", "/projects/nonexistent")
    assert resp.status == 404


# ---------------------------------------------------------------------------
# Phase 3: triggers
# ---------------------------------------------------------------------------


def test_triggers_create_and_list(patched_services, client):
    """AC-23: POST /triggers creates a trigger; GET /triggers lists it."""
    resp = client(
        "POST",
        "/triggers",
        body={"plan": [{"skill": "alpha"}], "cron": "*/5 * * * *"},
    )
    assert resp.status == 201
    trigger = _json(resp)
    assert trigger["trigger_type"] == "cron"
    assert trigger["config"]["cron"] == "*/5 * * * *"
    trigger_id = trigger["trigger_id"]

    resp = client("GET", "/triggers")
    assert resp.status == 200
    ids = [t["trigger_id"] for t in _json(resp)["triggers"]]
    assert trigger_id in ids


def test_triggers_create_manual(patched_services, client):
    """AC-23: POST /triggers without cron creates a manual trigger."""
    resp = client("POST", "/triggers", body={"plan": [{"skill": "alpha"}]})
    assert resp.status == 201
    assert _json(resp)["trigger_type"] == "manual"


def test_triggers_show(patched_services, client):
    """AC-23: GET /triggers/{id} returns trigger detail."""
    resp = client("POST", "/triggers", body={"plan": [{"skill": "alpha"}]})
    trigger_id = _json(resp)["trigger_id"]
    resp = client("GET", f"/triggers/{trigger_id}")
    assert resp.status == 200
    assert _json(resp)["trigger_id"] == trigger_id


def test_triggers_delete(patched_services, client):
    """AC-23: DELETE /triggers/{id} removes the trigger."""
    resp = client("POST", "/triggers", body={"plan": [{"skill": "alpha"}]})
    trigger_id = _json(resp)["trigger_id"]
    resp = client("DELETE", f"/triggers/{trigger_id}")
    assert resp.status == 204
    assert client("GET", f"/triggers/{trigger_id}").status == 404


def test_triggers_fire(patched_services, client):
    """AC-23: POST /triggers/{id}/fire instantiates a job into the queue."""
    resp = client("POST", "/triggers", body={"plan": [{"skill": "alpha"}]})
    trigger_id = _json(resp)["trigger_id"]
    resp = client("POST", f"/triggers/{trigger_id}/fire")
    assert resp.status == 200
    assert _json(resp)["fired"] == trigger_id
    # The fired job should appear in the job store.
    assert len(_json(client("GET", "/jobs"))["jobs"]) >= 1


def test_triggers_fire_missing_404(patched_services, client):
    resp = client("POST", "/triggers/nonexistent/fire")
    assert resp.status == 404


# ---------------------------------------------------------------------------
# Phase 3: sync
# ---------------------------------------------------------------------------


def test_sync_memory_between_projects(patched_services, client, tmp_path):
    """AC-23: POST /sync propagates memory facts from source to target."""
    # Create source + target local projects with isolated state dirs.
    src_dir = tmp_path / "src-state"
    src_dir.mkdir()
    tgt_dir = tmp_path / "tgt-state"
    tgt_dir.mkdir()
    src = _json(
        client(
            "POST",
            "/projects",
            body={"name": "Src", "type": "local", "state_dir": str(src_dir)},
        )
    )["id"]
    tgt = _json(
        client(
            "POST",
            "/projects",
            body={"name": "Tgt", "type": "local", "state_dir": str(tgt_dir)},
        )
    )["id"]

    # Record a fact in the source project via the router's runtime.
    center = patched_services["center"]
    src_rt = center.router.resolve(src)
    src_rt.memory().remember_fact("shared_key", "shared_value")

    resp = client(
        "POST",
        "/sync",
        body={"source": src, "targets": [tgt], "scope": "memory"},
    )
    assert resp.status == 200
    data = _json(resp)
    assert data["scope"] == "memory"
    assert data["synced_count"] >= 1
    # The target should now have the fact.
    tgt_rt = center.router.resolve(tgt)
    assert tgt_rt.memory().get_fact("shared_key") is not None


def test_sync_validates_body(patched_services, client):
    """AC-23: POST /sync without source/targets returns 400."""
    resp = client("POST", "/sync", body={})
    assert resp.status == 400


# ---------------------------------------------------------------------------
# Phase 3: job status SSE
# ---------------------------------------------------------------------------


def test_stream_jobs_sse_connects(patched_services, server):
    """AC-21: GET /stream/jobs opens an SSE connection and sends a comment."""
    host, port = server.server_address[:2]
    conn = http.client.HTTPConnection(host, port, timeout=3)
    conn.request("GET", "/stream/jobs")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"
    # read1() returns whatever the server has already flushed (the initial
    # ": connected" comment) without blocking for the full amt — required
    # because the SSE handler only emits heartbeats every 15s.
    chunk = resp.read1(64)
    assert b"connected" in chunk
    conn.close()


# ---------------------------------------------------------------------------
# Todos (U7) routes
# ---------------------------------------------------------------------------


def test_todos_create_list_get(patched_services, client):
    resp = client("POST", "/todos", body={"title": "写一篇关于博若莱的文章", "type": "idea"})
    assert resp.status == 201
    todo = _json(resp)
    assert todo["title"] == "写一篇关于博若莱的文章"
    todo_id = todo["todo_id"]

    resp = client("GET", "/todos")
    assert resp.status == 200
    data = _json(resp)
    assert any(t["todo_id"] == todo_id for t in data["todos"])

    resp = client("GET", f"/todos/{todo_id}")
    assert resp.status == 200
    assert _json(resp)["status"] == "PENDING"


def test_todos_filter_by_status(patched_services, client):
    client("POST", "/todos", body={"title": "a"})
    client("POST", "/todos", body={"title": "b"})
    client("GET", "/todos")
    todos = _json(client("GET", "/todos"))["todos"]
    assert len(todos) == 2
    done = [t for t in todos][0]
    resp = client("POST", f"/todos/{done['todo_id']}/status", body={"status": "done"})
    assert resp.status == 200
    remaining = _json(client("GET", "/todos?status=PENDING"))["todos"]
    assert len(remaining) == 1


def test_todos_handoff_creates_job(patched_services, client):
    resp = client("POST", "/todos", body={"title": "handoff me"})
    todo = _json(resp)
    resp = client("POST", f"/todos/{todo['todo_id']}/hand-off", body={"plan": [{"skill": "alpha"}]})
    assert resp.status == 200
    data = _json(resp)
    assert data["todo_id"] == todo["todo_id"]
    assert data["job_id"]

    fetched = _json(client("GET", f"/todos/{todo['todo_id']}"))
    assert fetched["status"] == "HANDED_OFF"
    assert fetched["job_id"] == data["job_id"]

    # job is registered in the shared scheduler center
    resp = client("GET", "/jobs")
    assert resp.status == 200
    jobs = _json(resp)["jobs"]
    assert any(j["job_id"] == data["job_id"] for j in jobs)


def test_todos_handoff_invalid_plan(patched_services, client):
    resp = client("POST", "/todos", body={"title": "x"})
    todo = _json(resp)
    resp = client("POST", f"/todos/{todo['todo_id']}/hand-off", body={"plan": "not-a-list"})
    assert resp.status == 400


def test_todos_delete(patched_services, client):
    resp = client("POST", "/todos", body={"title": "gone"})
    todo = _json(resp)
    resp = client("DELETE", f"/todos/{todo['todo_id']}")
    assert resp.status == 204
    resp = client("GET", f"/todos/{todo['todo_id']}")
    assert resp.status == 404
