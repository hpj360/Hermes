"""Tests for cache-aware context maintenance (A1/A3) — src/hermes/context.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes import context as ctx


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text("# conventions\nkeep it simple", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def _summary_dir_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ctx, "_summary_dir", lambda: tmp_path)


def test_env_summary_stable_and_cached(repo, tmp_path, monkeypatch):
    _summary_dir_to(tmp_path, monkeypatch)
    first = ctx.env_summary(repo)
    second = ctx.env_summary(repo)
    assert first == second
    assert first["version"]
    assert "keep it simple" in first["conventions"]
    assert "src" in first["structure"]
    # cache file written
    assert (tmp_path / "context-summary.json").exists()


def test_env_summary_recomputes_on_change(repo, tmp_path, monkeypatch):
    _summary_dir_to(tmp_path, monkeypatch)
    v1 = ctx.env_summary(repo)
    (repo / "AGENTS.md").write_text("# changed", encoding="utf-8")
    v2 = ctx.env_summary(repo)
    assert v1["version"] != v2["version"]


def test_build_stable_prefix_fixed_order(repo):
    env = ctx.env_summary(repo)
    prefix = ctx.build_stable_prefix("def", env=env)
    assert prefix.startswith("def")
    assert "keep it simple" in prefix
    # deterministic
    assert prefix == ctx.build_stable_prefix("def", env=env)


def test_build_stable_prefix_no_agent_def(repo):
    env = ctx.env_summary(repo)
    prefix = ctx.build_stable_prefix("", env=env)
    assert "keep it simple" in prefix


def test_assert_stable_prefix_passes_on_equal():
    ctx.assert_stable_prefix("same", "same")


def test_assert_stable_prefix_raises_on_change():
    with pytest.raises(ValueError):
        ctx.assert_stable_prefix("a", "b")


def test_prune_stale_tool_outputs_keeps_markers():
    msgs = [
        {"role": "user", "content": "task"},
        {"role": "tool", "content": "old read result"},
        {"role": "tool", "content": "check: FAILED"},
    ]
    pruned = ctx.prune_stale_tool_outputs(msgs, kept_markers=["FAILED"], keep_last=0)
    # user msg + the marker-hit tool msg survive
    assert any(m.get("content") == "check: FAILED" for m in pruned)
    assert not any(m.get("content") == "old read result" for m in pruned)


def test_prune_stale_tool_outputs_keeps_last():
    msgs = [
        {"role": "user", "content": "task"},
        {"role": "tool", "content": "old"},
        {"role": "tool", "content": "newest"},
    ]
    pruned = ctx.prune_stale_tool_outputs(msgs, kept_markers=[], keep_last=1)
    assert any(m.get("content") == "newest" for m in pruned)
    assert not any(m.get("content") == "old" for m in pruned)


def test_llm_chat_stable_prefix_prepended():
    from hermes.workbench.llm import LlmClient, LlmMessage, LlmResponse

    client = LlmClient(base_url="http://127.0.0.1:1", api_key=None, model="m")
    captured: dict = {}

    def fake_post(url, payload, timeout):
        captured["body"] = payload.decode("utf-8")
        return LlmResponse(content="ok")

    client._post_once = fake_post  # type: ignore[assignment]
    client.chat([LlmMessage(role="user", content="hi")], stable_prefix="STABLE")
    import json

    body = json.loads(captured["body"])
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == "STABLE"
    assert body["messages"][1]["role"] == "user"
