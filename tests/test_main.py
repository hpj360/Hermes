"""Tests for hermes.main CLI entry point and build_parser()."""

from __future__ import annotations

import argparse

import pytest

from hermes import main as hermes_main
from hermes.main import build_parser, main


@pytest.fixture(autouse=True)
def reset_settings_around():
    from hermes import config as _config
    _config._hermes_settings = None
    yield
    _config._hermes_settings = None


def test_main_start_returns_zero() -> None:
    assert main(["start"]) == 0


def test_main_skills_list_returns_zero() -> None:
    assert main(["skills", "list"]) == 0


def test_main_knowledge_list_returns_zero() -> None:
    assert main(["knowledge", "list"]) == 0


def test_main_config_show_returns_zero() -> None:
    assert main(["config", "show"]) == 0


def test_main_doctor_returns_zero_or_one() -> None:
    rc = main(["doctor"])
    assert rc in (0, 1)


def test_main_profile_show_returns_zero(tmp_state_dir) -> None:
    assert main(["profile", "show"]) == 0


def test_main_profile_show_json_returns_zero(tmp_state_dir) -> None:
    assert main(["profile", "show", "--json"]) == 0


def test_main_no_args_returns_zero() -> None:
    # No command → defaults to cmd_start
    assert main([]) == 0


def test_build_parser_has_workbench_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["workbench", "skills", "list"])
    assert args.command == "workbench"


def test_main_workbench_skills_list_returns_zero() -> None:
    rc = main(["workbench", "skills", "list"])
    assert rc == 0


def test_main_returns_2_on_exception(monkeypatch) -> None:
    def boom(args: argparse.Namespace) -> int:
        raise RuntimeError("intentional")

    monkeypatch.setattr(hermes_main, "cmd_start", boom)
    # build_parser assigns cmd_start via set_defaults at parser-build time, so
    # patching the symbol first makes the parser bind the raising function.
    assert main(["start"]) == 2


def test_log_level_choices_exist() -> None:
    parser = build_parser()
    # Valid choices parse fine
    args = parser.parse_args(["--log-level", "DEBUG", "start"])
    assert args.log_level == "DEBUG"
    # Invalid choice causes SystemExit (argparse error)
    with pytest.raises(SystemExit):
        parser.parse_args(["--log-level", "BOGUS", "start"])


# ── dump-config (ADR-0019: effective runtime composition view) ──


def test_main_dump_config_returns_zero() -> None:
    assert main(["dump-config"]) == 0


def test_main_dump_config_json_returns_zero() -> None:
    assert main(["dump-config", "--json"]) == 0


def test_build_parser_has_dump_config_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["dump-config"])
    assert args.command == "dump-config"


def test_dump_config_contains_all_sections(capsys) -> None:
    main(["dump-config"])
    out = capsys.readouterr().out
    # 每个 section header 必须出现（回答 DSH 三问之①：运行时最终加载了什么）
    for section in [
        "[paths]",
        "[models]",
        "[gateway]",
        "[loop_patterns]",
        "[agent_presets]",
        "[skills]",
        "[denylist_aggregate]",
    ]:
        assert section in out, f"missing section: {section}"


def test_dump_config_json_is_parseable(capsys) -> None:
    import json

    main(["dump-config", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    # 顶层键覆盖全部组装维度
    expected_keys = {
        "paths",
        "models",
        "gateway",
        "loop_patterns",
        "agent_presets",
        "skills",
        "denylist_aggregate",
    }
    assert expected_keys.issubset(payload.keys())


def test_dump_config_denylist_includes_default(capsys) -> None:
    """denylist 聚合必须含 DEFAULT_DENYLIST（L3 红线不可丢失）。"""
    from hermes.gepa_redteam import DEFAULT_DENYLIST

    main(["dump-config", "--json"])
    import json

    out = capsys.readouterr().out
    payload = json.loads(out)
    aggregated = set(payload["denylist_aggregate"])
    for pattern in DEFAULT_DENYLIST:
        assert pattern in aggregated, f"DEFAULT_DENYLIST pattern lost: {pattern}"


def test_dump_config_denylist_is_union(capsys) -> None:
    """聚合 denylist = DEFAULT ∪ LOOP_PATTERNS[*].denylist ∪ presets[*].denylist。"""
    from hermes.gepa_redteam import DEFAULT_DENYLIST
    from hermes.loop import LOOP_PATTERNS
    from hermes.presets import merged_presets

    expected: set[str] = set(DEFAULT_DENYLIST)
    for p in LOOP_PATTERNS.values():
        expected.update(p.get("denylist", []))
    for preset in merged_presets().values():
        expected.update(preset.denylist)

    main(["dump-config", "--json"])
    import json

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert set(payload["denylist_aggregate"]) == expected


def test_dump_config_loop_patterns_count_matches_source(capsys) -> None:
    from hermes.loop import LOOP_PATTERNS

    main(["dump-config", "--json"])
    import json

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert len(payload["loop_patterns"]) == len(LOOP_PATTERNS)
