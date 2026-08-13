"""Tests for `hermes` power subcommands: sh / diff / context / init.

Covers all four power commands registered in cli_power.py. Isolates:
- shell commands via real deterministic binaries (echo/false) — no git dependency.
- git diff via monkeypatching subprocess.run — does not depend on real git state.
- loop context via the tmp_loops monkeypatch (mirrors test_cli_loop.py).
- init via an isolated tmp project root + settings reload.
"""

from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest

from hermes import loop as loop_mod
from hermes.cli_power import add_power_subparser, cmd_sh
from hermes.main import build_parser, main


@pytest.fixture(autouse=True)
def reset_settings_around() -> Any:
    """每个测试前后清理 settings 单例，避免 env 跨测试污染。"""
    from hermes import config as _config
    _config._hermes_settings = None
    yield
    _config._hermes_settings = None


@pytest.fixture
def tmp_loops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """将 hermes.loop.loops_dir() 重定向到隔离的 tmp 目录。

    loops_dir() 默认返回 _project_root()/".loops"，不读 HERMES_STATE_DIR，
    因此用 monkeypatch（与 test_cli_loop.py 同模式）。
    """
    loops = tmp_path / ".loops"
    loops.mkdir()
    monkeypatch.setattr(loop_mod, "loops_dir", lambda: loops)
    return loops


@pytest.fixture
def tmp_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """将 HERMES_PROJECT_ROOT 指向 tmp_path 并创建骨架目录，供 init 测试。"""
    monkeypatch.setenv("HERMES_PROJECT_ROOT", str(tmp_path))
    from hermes.config import get_settings
    get_settings(force_reload=True)
    # 创建关键目录，验证骨架扫描逻辑
    (tmp_path / "src" / "hermes").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "scripts").mkdir()
    return tmp_path


def _fake_completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> CompletedProcess[str]:
    """构造一个假的 CompletedProcess 用于 mock subprocess.run。"""
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ── Parser registration ────────────────────────────────────────────


@pytest.mark.parametrize("sub", ["sh", "diff", "context", "init"])
def test_power_subcommands_registered(sub: str) -> None:
    """四个 power 子命令都注册到顶层 subparser。"""
    parser = build_parser()
    args = parser.parse_args([sub])
    assert args.command == sub


def test_add_power_subparser_idempotent() -> None:
    """add_power_subparser 可独立调用并注册全部 4 个命令。"""
    import argparse as _ap
    parser = _ap.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="command", required=False)
    add_power_subparser(sub)
    for name in ("sh", "diff", "context", "init"):
        assert parser.parse_args([name]).command == name


# ── sh ─────────────────────────────────────────────────────────────


def test_sh_executes_command(capsys: pytest.CaptureFixture[str]) -> None:
    """`hermes sh 'echo hello'` 回显命令输出，返回 0。"""
    rc = main(["sh", "echo hello"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hello" in out


def test_sh_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    """`--json` 输出含 exit_code/stdout/stderr 的结构化 JSON。"""
    rc = main(["sh", "echo hello", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["exit_code"] == 0
    assert "hello" in data["stdout"]
    assert "stderr" in data


def test_sh_nonzero_exit_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    """命令本身返回非零时，cmd_sh 返回 1（soft fail）。"""
    rc = main(["sh", "false"])
    assert rc == 1


def test_sh_missing_command_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """缺少 command 参数时返回 2（hard error），不崩溃。"""
    rc = main(["sh"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "requires a command" in out


def test_sh_handler_directly() -> None:
    """直接调用 handler 验证返回码映射（不经 main 兜底）。"""
    import argparse as _ap
    ns = _ap.Namespace(shell_command="echo ok", json=False)
    assert cmd_sh(ns) == 0


# ── diff ───────────────────────────────────────────────────────────


def test_diff_shows_unstaged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`hermes diff` 调用 git diff 并回显输出。"""
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> CompletedProcess[str]:
        captured["cmd"] = cmd
        return _fake_completed(stdout="@@ -1 +1 @@", returncode=0)

    monkeypatch.setattr("hermes.cli_power.subprocess.run", fake_run)
    rc = main(["diff"])
    assert rc == 0
    assert captured["cmd"] == ["git", "diff"]
    assert "@@ -1 +1 @@" in capsys.readouterr().out


def test_diff_staged_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--staged` 透传给 git diff。"""
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> CompletedProcess[str]:
        captured["cmd"] = cmd
        return _fake_completed(stdout="staged diff", returncode=0)

    monkeypatch.setattr("hermes.cli_power.subprocess.run", fake_run)
    assert main(["diff", "--staged"]) == 0
    assert captured["cmd"] == ["git", "diff", "--staged"]
    assert "staged diff" in capsys.readouterr().out


def test_diff_stat_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--stat` 透传给 git diff。"""
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> CompletedProcess[str]:
        captured["cmd"] = cmd
        return _fake_completed(stdout="1 file changed", returncode=0)

    monkeypatch.setattr("hermes.cli_power.subprocess.run", fake_run)
    assert main(["diff", "--stat"]) == 0
    assert captured["cmd"] == ["git", "diff", "--stat"]
    assert "file changed" in capsys.readouterr().out


def test_diff_nonzero_returns_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """git 非零退出（如非 git 仓库）时返回 1。"""
    monkeypatch.setattr(
        "hermes.cli_power.subprocess.run",
        lambda cmd, **kw: _fake_completed(stderr="not a git repo", returncode=128),
    )
    assert main(["diff"]) == 1


# ── context ─────────────────────────────────────────────────────────


def test_context_no_args_lists_loops(
    tmp_loops: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """无参数时列出所有 loop 概览。"""
    main(["loop", "init", "ctx-loop"])
    capsys.readouterr()  # 清掉 init 输出
    rc = main(["context"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ctx-loop" in out
    assert "Active loops" in out


def test_context_no_loops_message(
    tmp_loops: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """无 loop 时给出友好提示，返回 0。"""
    rc = main(["context"])
    assert rc == 0
    assert "No loops found" in capsys.readouterr().out


def test_context_with_name_shows_detail(
    tmp_loops: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """指定 loop-name 时显示详细状态。"""
    main(["loop", "init", "detail-loop"])
    capsys.readouterr()
    rc = main(["context", "detail-loop"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "detail-loop" in out
    assert "Pattern:" in out
    assert "Status:" in out
    assert "Budget:" in out


def test_context_nonexistent_loop_errors(
    tmp_loops: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """查询不存在的 loop 返回 1。"""
    rc = main(["context", "no-such-loop"])
    assert rc == 1
    assert "not found" in capsys.readouterr().out


# ── init ───────────────────────────────────────────────────────────


def test_init_generates_agents_md(
    tmp_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AGENTS.md 不存在时生成骨架文件。"""
    agents = tmp_project / "AGENTS.md"
    assert not agents.exists()
    rc = main(["init"])
    assert rc == 0
    assert agents.exists()
    content = agents.read_text(encoding="utf-8")
    assert "AGENTS.md" in content
    assert "项目概述" in content
    assert "目录结构" in content
    assert "开发命令" in content
    # 扫描到的目录应出现在骨架里
    assert "src/hermes" in content
    assert "skills" in content
    assert "Generated" in capsys.readouterr().out


def test_init_existing_agents_md_does_not_overwrite(
    tmp_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AGENTS.md 已存在时不覆盖，仅提示。"""
    agents = tmp_project / "AGENTS.md"
    original = "# My custom AGENTS.md\n用户自定义内容\n"
    agents.write_text(original, encoding="utf-8")

    rc = main(["init"])
    assert rc == 0
    # 内容未被覆盖
    assert agents.read_text(encoding="utf-8") == original
    out = capsys.readouterr().out
    assert "already exists" in out
    assert "Not overwriting" in out


def test_init_skeleton_includes_dev_commands(tmp_project: Path) -> None:
    """生成的骨架包含 pip install / pytest / ruff / mypy 命令。"""
    main(["init"])
    content = (tmp_project / "AGENTS.md").read_text(encoding="utf-8")
    assert "pip install" in content
    assert "ruff" in content
    assert "mypy" in content


# ── deploy ──────────────────────────────────────────────────────────


def test_deploy_generates_assets(tmp_project: Path) -> None:
    """`hermes deploy` 应生成 Dockerfile / docker-compose.yml / README.md。"""
    rc = main(["deploy"])
    assert rc == 0
    deploy_dir = tmp_project / "deploy"
    assert (deploy_dir / "Dockerfile").exists()
    assert (deploy_dir / "docker-compose.yml").exists()
    assert (deploy_dir / "README.md").exists()
    content = (deploy_dir / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python" in content


def test_deploy_custom_output_dir(tmp_project: Path) -> None:
    """`hermes deploy --output <dir>` 应写到指定目录。"""
    custom = tmp_project / "custom-deploy"
    rc = main(["deploy", "--output", str(custom)])
    assert rc == 0
    assert (custom / "Dockerfile").exists()
