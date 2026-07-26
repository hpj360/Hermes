"""Subprocess wrapper for the `skill-up` Go binary.

All skill-up invocations go through SkillUpClient. The client is a thin
wrapper — it builds argv, runs subprocess, and returns CompletedProcess.
Result parsing lives in result.py; orchestration lives in runner.py.

The client takes an injectable ``run_fn`` so tests can mock subprocess
without monkeypatching the module globally.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger("hermes.eval.client")


class SkillUpError(Exception):
    """skill-up invocation failed (non-zero exit or binary error)."""


class SkillUpNotFoundError(SkillUpError):
    """skill-up binary not found on PATH or at configured path."""


# Type alias for the subprocess runner injection point.
# Signature mirrors subprocess.run(...)->CompletedProcess.
RunFn = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass
class SkillUpClient:
    """Thin subprocess wrapper around the skill-up CLI.

    Args:
        binary: Name or path of the skill-up binary. Default "skill-up"
            (resolved via PATH). Override with SKILL_UP_BINARY env var
            or explicit path for pinned installs.
        run_fn: Subprocess executor. Defaults to subprocess.run. Tests
            inject a fake to avoid needing the real binary.
        default_timeout: Default per-invocation timeout in seconds.
    """

    binary: str = "skill-up"
    run_fn: RunFn = field(default=subprocess.run)
    default_timeout: float = 600.0

    def __post_init__(self) -> None:
        # If binary is a bare name (no path separator), check PATH once
        # at construction so is_available() is cheap on repeated calls.
        # We don't cache the result — PATH may change in long-lived procs.
        pass

    def is_available(self) -> bool:
        """Check if the skill-up binary is available.

        Returns False (not raises) when missing — callers use this to
        decide whether to fall back to guidance mode.
        """
        if "/" in self.binary or "\\" in self.binary:
            # Explicit path: check file exists and is executable
            p = Path(self.binary)
            return p.exists() and p.stat().st_mode & 0o111 != 0
        return shutil.which(self.binary) is not None

    def _build_argv(self, subcommand: str, *args: str) -> list[str]:
        """Build argv list. Centralized so escaping is consistent."""
        return [self.binary, subcommand, *args]

    def _invoke(
        self,
        argv: list[str],
        timeout: float | None = None,
        cwd: str | Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run skill-up with argv. Raises SkillUpError on failure.

        We capture stdout+stderr together to preserve ordering for
        error messages. check=False — caller inspects returncode.
        """
        if not self.is_available():
            raise SkillUpNotFoundError(
                f"skill-up binary not found at '{self.binary}'. "
                "Install via: curl -fsSL https://raw.githubusercontent.com/"
                "alibaba/skill-up/main/install.sh | bash"
            )

        effective_timeout = timeout if timeout is not None else self.default_timeout
        logger.debug("skill-up invoke: %s (cwd=%s, timeout=%s)", argv, cwd, effective_timeout)
        try:
            result = self.run_fn(
                argv,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=str(cwd) if cwd else None,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SkillUpError(
                f"skill-up timed out after {effective_timeout}s: {' '.join(argv)}"
            ) from exc
        except OSError as exc:
            raise SkillUpError(f"skill-up invocation failed: {exc}") from exc

        return result

    # ── Subcommand wrappers ────────────────────────────────────────────

    def run(
        self,
        eval_path: str | Path,
        *,
        include_case: list[str] | None = None,
        exclude_case: list[str] | None = None,
        fmt: list[str] | None = None,
        output_dir: str | Path | None = None,
        iteration: int | None = None,
        engine: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        cwd: str | Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Wrapper for `skill-up run [path] [flags]`.

        Returns CompletedProcess (caller parses result.json from output_dir).
        Raises SkillUpError on non-zero exit (after the call — we don't
        raise on non-zero because some failures are partial passes).
        """
        argv = self._build_argv("run", str(eval_path))
        if include_case:
            for c in include_case:
                argv.extend(["--include-case-name", c])
        if exclude_case:
            for c in exclude_case:
                argv.extend(["--exclude-case-name", c])
        if fmt:
            for f in fmt:
                argv.extend(["--format", f])
        if output_dir:
            argv.extend(["--output-dir", str(output_dir)])
        if iteration is not None:
            argv.extend(["--iteration", str(iteration)])
        if engine:
            argv.extend(["--engine", engine])
        if model:
            argv.extend(["--model", model])

        return self._invoke(argv, timeout=timeout, cwd=cwd)

    def validate(
        self,
        eval_path: str | Path,
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Wrapper for `skill-up validate [path]`. Only checks config."""
        argv = self._build_argv("validate", str(eval_path))
        return self._invoke(argv, timeout=timeout, cwd=cwd)

    def list_cases(
        self,
        eval_path: str | Path,
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Wrapper for `skill-up list-cases [path]`."""
        argv = self._build_argv("list-cases", str(eval_path))
        return self._invoke(argv, timeout=timeout, cwd=cwd)

    def report(
        self,
        workspace: str | Path,
        *,
        fmt: list[str] | None = None,
        cwd: str | Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Wrapper for `skill-up report [workspace]`."""
        argv = self._build_argv("report", str(workspace))
        if fmt:
            for f in fmt:
                argv.extend(["--format", f])
        return self._invoke(argv, timeout=timeout, cwd=cwd)

    def version(self) -> str:
        """Get skill-up version string. Returns "unknown" on error."""
        if not self.is_available():
            return "unknown"
        try:
            result = self._invoke(self._build_argv("--version"), timeout=10.0)
            return (result.stdout or "unknown").strip()
        except SkillUpError:
            return "unknown"
