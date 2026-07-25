"""Tests for `hermes loop <sub>` CLI commands.

Covers all 13 loop subcommands registered in cli_loop.py. Isolates the loops
directory via monkeypatch (loops_dir() returns _project_root()/".loops" and
does not respect HERMES_STATE_DIR, so we patch it to a tmp path).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from hermes import loop as loop_mod
from hermes.main import build_parser, main
from hermes.cli_loop import (
    add_loop_subparser,
    cmd_loop_list,
    cmd_loop_stop_rules,
    cmd_loop_patterns,
)


@pytest.fixture(autouse=True)
def reset_settings_around():
    from hermes import config as _config
    _config._hermes_settings = None
    yield
    _config._hermes_settings = None


@pytest.fixture
def tmp_loops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect hermes.loop.loops_dir() to an isolated tmp directory.

    loops_dir() returns _project_root()/".loops" by default and does not
    respect HERMES_STATE_DIR. test_loop.py uses the same monkeypatch pattern.
    """
    loops = tmp_path / ".loops"
    loops.mkdir()
    monkeypatch.setattr(loop_mod, "loops_dir", lambda: loops)
    return loops


def _ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace with default json=False for handler tests."""
    return argparse.Namespace(json=False, **kwargs)


# ── Parser registration tests ───────────────────────────────────────


def test_build_parser_has_loop_subcommand() -> None:
    """`hermes loop` is registered as a top-level subcommand."""
    parser = build_parser()
    args = parser.parse_args(["loop", "list"])
    assert args.command == "loop"
    assert args.loop_cmd == "list"


def test_loop_subcommand_requires_subcommand() -> None:
    """`hermes loop` without a subcommand exits (argparse required=True)."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["loop"])


@pytest.mark.parametrize("sub", [
    "list", "init", "run", "continuous", "resume", "audit",
    "status", "metrics", "stop-rules", "budget", "advance", "history", "patterns",
])
def test_all_loop_subcommands_registered(sub: str) -> None:
    """All 13 loop subcommands are registered and parseable."""
    parser = build_parser()
    # Commands that need a name arg
    if sub in ("init", "run", "continuous", "resume", "status", "metrics", "budget", "advance", "history"):
        args = parser.parse_args(["loop", sub, "test-loop"])
    elif sub == "audit":
        args = parser.parse_args(["loop", sub])  # name is optional
    else:
        args = parser.parse_args(["loop", sub])
    assert args.loop_cmd == sub


# ── list ────────────────────────────────────────────────────────────


def test_loop_list_empty_returns_zero(tmp_loops, capsys) -> None:
    """`hermes loop list` with no loops prints helpful message, returns 0."""
    rc = main(["loop", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No loops found" in out


def test_loop_list_after_init_shows_loop(tmp_loops, capsys) -> None:
    """After init, `hermes loop list` shows the created loop."""
    assert main(["loop", "init", "my-loop", "--pattern", "builder-checker"]) == 0
    rc = main(["loop", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "my-loop" in out
    assert "builder-checker" in out


def test_loop_list_json_output(tmp_loops, capsys) -> None:
    """`--json` flag produces valid JSON."""
    main(["loop", "init", "json-loop"])
    capsys.readouterr()  # clear init output
    assert main(["loop", "list", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "json-loop"


# ── init ────────────────────────────────────────────────────────────


def test_loop_init_creates_loop(tmp_loops, capsys) -> None:
    """`hermes loop init` creates a loop directory."""
    rc = main(["loop", "init", "new-loop", "--pattern", "custom"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Initialized loop 'new-loop'" in out


def test_loop_init_duplicate_fails(tmp_loops, capsys) -> None:
    """Initializing an existing loop name fails with exit 1."""
    main(["loop", "init", "dup-loop"])
    rc = main(["loop", "init", "dup-loop"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "already exists" in out


def test_loop_init_with_pattern(tmp_loops, capsys) -> None:
    """init with a known pattern succeeds."""
    rc = main(["loop", "init", "bc-loop", "--pattern", "builder-checker"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "builder-checker" in out


# ── status ──────────────────────────────────────────────────────────


def test_loop_status_existing_loop(tmp_loops, capsys) -> None:
    """`hermes loop status` shows loop state."""
    main(["loop", "init", "status-loop"])
    rc = main(["loop", "status", "status-loop"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status-loop" in out
    assert "Pattern:" in out
    assert "Status:" in out


def test_loop_status_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """`hermes loop status` on missing loop returns 1."""
    rc = main(["loop", "status", "no-such-loop"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "not found" in out


def test_loop_status_json_output(tmp_loops, capsys) -> None:
    """`--json` flag produces valid JSON with loop fields."""
    main(["loop", "init", "j-loop"])
    capsys.readouterr()  # clear init output
    assert main(["loop", "status", "j-loop", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["name"] == "j-loop"
    assert "pattern" in data
    assert "stage" in data
    assert "status" in data


# ── audit ───────────────────────────────────────────────────────────


def test_loop_audit_all_loops(tmp_loops, capsys) -> None:
    """`hermes loop audit` (no name) audits all loops."""
    main(["loop", "init", "a1"])
    rc = main(["loop", "audit"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Loop Audit" in out


def test_loop_audit_specific_loop(tmp_loops, capsys) -> None:
    """`hermes loop audit <name>` audits a specific loop."""
    main(["loop", "init", "a2"])
    rc = main(["loop", "audit", "a2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a2" in out


def test_loop_audit_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """Auditing a nonexistent loop returns 1."""
    rc = main(["loop", "audit", "ghost"])
    assert rc == 1


def test_loop_audit_no_loops_returns_zero(tmp_loops, capsys) -> None:
    """Auditing with no loops returns 0 with helpful message."""
    rc = main(["loop", "audit"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No loops" in out or "score: 0" in out


# ── metrics ─────────────────────────────────────────────────────────


def test_loop_metrics_existing_loop(tmp_loops, capsys) -> None:
    """`hermes loop metrics` shows aggregated metrics."""
    main(["loop", "init", "m-loop"])
    rc = main(["loop", "metrics", "m-loop"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Metrics for loop 'm-loop'" in out
    assert "Total rounds:" in out


def test_loop_metrics_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """Metrics on missing loop returns 1."""
    rc = main(["loop", "metrics", "ghost"])
    assert rc == 1


def test_loop_metrics_json_output(tmp_loops, capsys) -> None:
    """`--json` produces valid JSON metrics."""
    main(["loop", "init", "mj-loop"])
    capsys.readouterr()  # clear init output
    assert main(["loop", "metrics", "mj-loop", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert data["loop"] == "mj-loop"


# ── budget ──────────────────────────────────────────────────────────


def test_loop_budget_existing_loop(tmp_loops, capsys) -> None:
    """`hermes loop budget` shows budget status."""
    main(["loop", "init", "b-loop"])
    rc = main(["loop", "budget", "b-loop"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Budget for loop 'b-loop'" in out
    assert "Level:" in out


def test_loop_budget_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """Budget on missing loop returns 1."""
    rc = main(["loop", "budget", "ghost"])
    assert rc == 1


# ── stop-rules ──────────────────────────────────────────────────────


def test_loop_stop_rules_prints_all_rules(tmp_loops, capsys) -> None:
    """`hermes loop stop-rules` prints all 7 stop rules."""
    rc = main(["loop", "stop-rules"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Stop Rules (7)" in out
    assert "all_green" in out
    assert "regression" in out
    assert "[HARD]" in out


def test_loop_stop_rules_json_output(tmp_loops, capsys) -> None:
    """`--json` flag produces valid JSON array of rules."""
    assert main(["loop", "stop-rules", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) == 7
    assert any(r["id"] == "all_green" for r in data)


# ── patterns ────────────────────────────────────────────────────────


def test_loop_patterns_prints_all(tmp_loops, capsys) -> None:
    """`hermes loop patterns` lists all registered patterns."""
    rc = main(["loop", "patterns"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Loop Patterns" in out
    assert "builder-checker" in out
    assert "knowledge-hygiene" in out


def test_loop_patterns_json_output(tmp_loops, capsys) -> None:
    """`--json` flag produces valid JSON."""
    assert main(["loop", "patterns", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert len(data) > 0
    keys = {p["key"] for p in data}
    assert "builder-checker" in keys


# ── history ─────────────────────────────────────────────────────────


def test_loop_history_existing_loop(tmp_loops, capsys) -> None:
    """`hermes loop history` shows round history (empty for new loop)."""
    main(["loop", "init", "h-loop"])
    rc = main(["loop", "history", "h-loop"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "History for loop 'h-loop'" in out


def test_loop_history_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """History on missing loop returns 1."""
    rc = main(["loop", "history", "ghost"])
    assert rc == 1


# ── advance ─────────────────────────────────────────────────────────


def test_loop_advance_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """Advancing a nonexistent loop returns 1."""
    rc = main(["loop", "advance", "ghost"])
    assert rc == 1


# ── run / continuous / resume ───────────────────────────────────────
# These invoke runner functions which depend on the Gateway. In test
# environments without a Gateway, they return guidance mode or an error,
# but should not crash. We assert they return a valid exit code (0 or 1).


def test_loop_run_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """Running a nonexistent loop returns 1 (not a crash)."""
    rc = main(["loop", "run", "ghost"])
    assert rc == 1
    assert "not found" in capsys.readouterr().out


def test_loop_continuous_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """Continuous run on nonexistent loop returns 1 (not a crash)."""
    rc = main(["loop", "continuous", "ghost"])
    assert rc == 1


def test_loop_resume_nonexistent_returns_1(tmp_loops, capsys) -> None:
    """Resuming a nonexistent loop returns 1 (not a crash)."""
    rc = main(["loop", "resume", "ghost"])
    assert rc == 1


# ── Direct handler tests (no argparse) ──────────────────────────────


def test_cmd_loop_stop_rules_handler_direct() -> None:
    """Handler can be called directly with a Namespace (no argparse)."""
    rc = cmd_loop_stop_rules(_ns())
    assert rc == 0


def test_cmd_loop_patterns_handler_direct() -> None:
    """Handler can be called directly with a Namespace."""
    rc = cmd_loop_patterns(_ns())
    assert rc == 0


def test_cmd_loop_list_handler_direct_empty(tmp_loops, capsys) -> None:
    """List handler returns 0 when no loops exist."""
    rc = cmd_loop_list(_ns())
    assert rc == 0


def test_add_loop_subparser_is_callable() -> None:
    """add_loop_subparser registers without error on a fresh subparsers."""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=False)
    add_loop_subparser(sub)
    args = parser.parse_args(["loop", "list"])
    assert args.loop_cmd == "list"
