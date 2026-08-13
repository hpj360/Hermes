"""Tests for hermes.workbench.sandbox (P2-2 AST static gate)."""

from __future__ import annotations

from pathlib import Path

from hermes.workbench.sandbox import (
    analyze_python_source,
    check_python_file,
)


# ---------------------------------------------------------------------------
# analyze_python_source
# ---------------------------------------------------------------------------


def _violations(source: str) -> list[str]:
    return [v.message for v in analyze_python_source(source)]


def test_clean_source_has_no_violations() -> None:
    assert analyze_python_source("import sys\nprint('ok')\n") == []


def test_import_subprocess_flagged() -> None:
    msgs = _violations("import subprocess\n")
    assert any("subprocess" in m for m in msgs)


def test_from_import_subprocess_flagged() -> None:
    msgs = _violations("from subprocess import run\n")
    assert any("subprocess" in m for m in msgs)


def test_import_socket_flagged() -> None:
    msgs = _violations("import socket\n")
    assert any("socket" in m for m in msgs)


def test_import_os_alone_is_allowed() -> None:
    assert analyze_python_source("import os\n") == []


def test_os_system_call_flagged() -> None:
    msgs = _violations("import os\nos.system('id')\n")
    assert any("os.system" in m for m in msgs)


def test_os_remove_call_flagged() -> None:
    msgs = _violations("import os\nos.remove('/tmp/x')\n")
    assert any("os.remove" in m for m in msgs)


def test_shutil_rmtree_call_flagged() -> None:
    msgs = _violations("import shutil\nshutil.rmtree('/tmp/x')\n")
    assert any("shutil.rmtree" in m for m in msgs)


def test_eval_flagged() -> None:
    msgs = _violations("eval('1+1')\n")
    assert any("eval" in m for m in msgs)


def test_exec_flagged() -> None:
    msgs = _violations("exec('x=1')\n")
    assert any("exec" in m for m in msgs)


def test_compile_flagged() -> None:
    msgs = _violations("compile('x', 'f', 'exec')\n")
    assert any("compile" in m for m in msgs)


def test_dunder_import_flagged() -> None:
    msgs = _violations("__import__('time')\n")
    assert any("__import__" in m for m in msgs)


def test_dunder_subclasses_flagged() -> None:
    msgs = _violations("x = ''.__class__.__mro__[1].__subclasses__()\n")
    assert any("__class__" in m for m in msgs)
    assert any("__mro__" in m for m in msgs)
    assert any("__subclasses__" in m for m in msgs)


def test_open_write_mode_flagged() -> None:
    assert any("open" in m for m in _violations("open('/tmp/x', 'w')\n"))
    assert any("open" in m for m in _violations("open('/tmp/x', 'a')\n"))


def test_open_read_mode_allowed() -> None:
    assert analyze_python_source("open('/tmp/x', 'r')\n") == []
    assert analyze_python_source("open('/tmp/x')\n") == []


def test_open_write_mode_kwarg_flagged() -> None:
    assert any("open" in m for m in _violations("open('/tmp/x', mode='w+')\n"))


def test_syntax_error_reported_as_violation() -> None:
    vs = analyze_python_source("def broken(:\n")
    assert len(vs) == 1
    assert "syntax error" in vs[0].message


# ---------------------------------------------------------------------------
# check_python_file
# ---------------------------------------------------------------------------


def test_check_python_file_clean(tmp_path: Path) -> None:
    f = tmp_path / "run.py"
    f.write_text("import sys\nprint('ok')\n", encoding="utf-8")
    report = check_python_file(f)
    assert report.clean is True


def test_check_python_file_flagged(tmp_path: Path) -> None:
    f = tmp_path / "run.py"
    f.write_text("import subprocess\n", encoding="utf-8")
    report = check_python_file(f)
    assert report.clean is False
    assert report.violations


def test_check_python_file_missing_degrades_clean(tmp_path: Path) -> None:
    report = check_python_file(tmp_path / "nope.py")
    assert report.clean is True
    assert report.violations == []


def test_check_python_file_unreadable_degrades_clean(tmp_path: Path) -> None:
    report = check_python_file(tmp_path)  # a directory, not a file
    assert report.clean is True
