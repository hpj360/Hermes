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
    return {"store": store, "registry": registry, "scheduler": scheduler}


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
    from hermes.workbench.memory import make_episode
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
