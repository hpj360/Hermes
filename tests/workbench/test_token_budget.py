"""Tests for the global daily LLM token budget (C4)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from hermes.workbench.llm import LlmClient, LlmMessage, _build_token_budget
from hermes.workbench.token_budget import (
    DailyTokenBudget,
    TokenBudgetExceeded,
    TokenUsageStore,
)


# ---------------------------------------------------------------------------
# TokenUsageStore
# ---------------------------------------------------------------------------


def test_store_records_and_snapshots(tmp_path) -> None:
    store = TokenUsageStore(tmp_path)
    store.record(100, 50)
    store.record(10, 5)
    snap = store.snapshot()
    assert snap.prompt_tokens == 110
    assert snap.completion_tokens == 55
    assert snap.total_tokens == 165
    assert snap.calls == 2


def test_store_persists_to_disk(tmp_path) -> None:
    TokenUsageStore(tmp_path).record(7, 3)
    raw = json.loads((tmp_path / TokenUsageStore.FILENAME).read_text(encoding="utf-8"))
    today = next(iter(raw.values()))
    assert today["prompt_tokens"] == 7 and today["completion_tokens"] == 3


def test_store_snapshot_absent_day_is_zero(tmp_path) -> None:
    snap = TokenUsageStore(tmp_path).snapshot(day="1999-01-01")
    assert snap.total_tokens == 0 and snap.calls == 0


def test_store_corrupt_file_degrades(tmp_path) -> None:
    (tmp_path / TokenUsageStore.FILENAME).write_text("{not json", encoding="utf-8")
    assert TokenUsageStore(tmp_path).snapshot().total_tokens == 0


# ---------------------------------------------------------------------------
# DailyTokenBudget
# ---------------------------------------------------------------------------


def test_budget_disabled_never_blocks(tmp_path) -> None:
    budget = DailyTokenBudget(TokenUsageStore(tmp_path), limit=0)
    budget.store.record(10_000, 10_000)
    budget.preflight()  # no raise


def test_budget_blocks_when_exhausted(tmp_path) -> None:
    budget = DailyTokenBudget(TokenUsageStore(tmp_path), limit=100)
    budget.preflight()  # under budget → ok
    budget.record(80, 40)  # now 120 >= 100
    with pytest.raises(TokenBudgetExceeded):
        budget.preflight()


def test_budget_usage_from_payload() -> None:
    assert DailyTokenBudget.usage_from_payload(
        {"usage": {"prompt_tokens": 12, "completion_tokens": 3}}
    ) == (12, 3)
    assert DailyTokenBudget.usage_from_payload({}) == (0, 0)
    assert DailyTokenBudget.usage_from_payload({"usage": "bad"}) == (0, 0)
    assert DailyTokenBudget.usage_from_payload(
        {"usage": {"prompt_tokens": None, "completion_tokens": "9"}}
    ) == (0, 9)


# ---------------------------------------------------------------------------
# LlmClient integration
# ---------------------------------------------------------------------------


def _mock_urlopen(data: dict[str, Any]) -> Any:
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_chat_records_usage(tmp_path) -> None:
    """chat() records the provider's usage into the budget ledger."""
    budget = DailyTokenBudget(TokenUsageStore(tmp_path), limit=1000)
    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        budget=budget,
    )
    payload = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 10},
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(payload)):
        client.chat([LlmMessage(role="user", content="hi")])
    assert budget.store.snapshot().total_tokens == 40


def test_chat_preflight_blocks_when_exhausted(tmp_path) -> None:
    """chat() refuses to call the provider once the budget is spent."""
    budget = DailyTokenBudget(TokenUsageStore(tmp_path), limit=10)
    budget.record(5, 5)  # exactly at limit
    client = LlmClient(
        base_url="https://api.example.com/v1", api_key="k", model="m", budget=budget
    )
    with patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(TokenBudgetExceeded):
            client.chat([LlmMessage(role="user", content="hi")])
    urlopen.assert_not_called()


def test_build_token_budget_disabled_and_enabled(tmp_path) -> None:
    off = SimpleNamespace(
        hermes_llm_daily_token_budget=0, hermes_state_dir=tmp_path
    )
    assert _build_token_budget(off) is None  # type: ignore[arg-type]
    on = SimpleNamespace(
        hermes_llm_daily_token_budget=500, hermes_state_dir=tmp_path
    )
    budget = _build_token_budget(on)  # type: ignore[arg-type]
    assert budget is not None and budget.limit == 500
