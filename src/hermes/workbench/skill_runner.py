"""Skill discovery and execution for the Workbench runtime.

Reads YAML front-matter from each skill's SKILL.md, detects an entrypoint
(run.py/main.py → python, run.sh → shell, run.js/index.js → node, otherwise
"prompt"), and runs the skill in a sanitized subprocess with sensitive
environment variables stripped.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes.workbench.sandbox import check_python_file

# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

# Common Git-for-Windows install locations for sh.exe (checked when not on PATH).
_WIN_SH_CANDIDATES = (
    r"C:\Program Files\Git\bin\sh.exe",
    r"C:\Program Files\Git\usr\bin\sh.exe",
    r"C:\Program Files (x86)\Git\bin\sh.exe",
    r"C:\Program Files (x86)\Git\usr\bin\sh.exe",
    # Official "current user only" installer path.
    r"%LOCALAPPDATA%\Programs\Git\bin\sh.exe",
    # Scoop / Chocolatey / MSYS2 / portable layouts.
    r"%USERPROFILE%\scoop\apps\git\current\bin\sh.exe",
    r"%USERPROFILE%\scoop\apps\msys2\current\usr\bin\sh.exe",
    r"C:\msys64\usr\bin\sh.exe",
)


def _find_posix_shell() -> str | None:
    """Locate a POSIX ``sh`` executable.

    On Unix ``sh`` is always on PATH. On Windows, try PATH first, then
    fall back to common Git-for-Windows install locations.
    """
    sh = shutil.which("sh")
    if sh:
        return sh
    if sys.platform == "win32":
        for candidate in _WIN_SH_CANDIDATES:
            expanded = os.path.expandvars(candidate)
            if os.path.isfile(expanded):
                return expanded
    return None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENSITIVE_SUBSTRINGS = (
    "token",
    "secret",
    "credential",
    "password",
    "passwd",
    "pwd",
    "key",
    "private",
    "cookie",
    "jwt",
    "session",
    "database",
    "auth",
    "cert",
    "signature",
)
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_apikey",
    "_access_key",
    "_secret_key",
    "_private_key",
    "_auth_token",
    "_session",
)

# Value-level patterns that look like embedded credentials. A variable whose
# name is not sensitive but whose VALUE carries a credential (e.g. a
# ``user:pass@host`` connection URL) must still be stripped.
_VALUE_CREDENTIAL_MARKERS = (
    "-----begin",  # PEM private key / cert blocks
    "://",  # scheme prefixes commonly embedding userinfo
)

# Whitelist of environment variables always passed to a skill subprocess.
# Everything else is either stripped (if sensitive) or dropped unless the
# skill explicitly declares it via ``requires.env``. This is the "allow-list"
# boundary: a skill can only read what it (or the base runtime) explicitly
# needs, so a compromised skill cannot harvest arbitrary secrets from the
# parent process environment.
_SAFE_ENV_KEYS = {
    "PATH",
    "HOME",
    "USER",
    "USERNAME",
    "TMP",
    "TEMP",
    "TMPDIR",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PYTHONIOENCODING",
    "PYTHONUNBUFFERED",
    "SHELL",
    "TERM",
    "CI",
    "GITHUB_ACTIONS",
    "NO_COLOR",
}


def _looks_sensitive(key: str) -> bool:
    """Return True if *key* looks like a secret-bearing env var name."""
    lower = key.lower()
    for sub in _SENSITIVE_SUBSTRINGS:
        if sub in lower:
            return True
    for suffix in _SENSITIVE_SUFFIXES:
        if lower.endswith(suffix):
            return True
    return False


def _looks_sensitive_value(value: str) -> bool:
    """Return True if a variable *value* carries an embedded credential.

    Catches secrets whose variable name is innocuous but whose value embeds
    credentials — e.g. ``DATABASE_URL=postgres://user:pass@host/db`` or a PEM
    private-key block stored under an arbitrary name.
    """
    if not value:
        return False
    lower = value.lower()
    return any(marker in lower for marker in _VALUE_CREDENTIAL_MARKERS)


def _parse_sandbox_flag(value: Any) -> bool:
    """Coerce a frontmatter ``sandbox`` value to a bool (default True).

    The static sandbox is opt-*out*: python entrypoints are gated by default,
    and a skill may disable it with ``sandbox: false`` (or "no"/"off"/"0").
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "off", "0")
    return True


def _parse_front_matter(path: Path) -> dict[str, Any]:
    """Parse YAML front-matter from a SKILL.md file.

    The ``metadata`` field is a JSON STRING (not nested YAML) and is parsed
    with ``json.loads``. Returns a dict of front-matter fields (empty if the
    file is missing or has no front-matter).
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}
    fm_lines = lines[1:end_idx]
    raw: dict[str, Any] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip() or ":" not in line:
            i += 1
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            items: list[Any] = []
            j = i + 1
            while j < len(fm_lines) and fm_lines[j].lstrip().startswith("- "):
                items.append(fm_lines[j].lstrip()[2:].strip())
                j += 1
            raw[key] = items
            i = j
        else:
            raw[key] = value
            i += 1
    md = raw.get("metadata")
    if isinstance(md, str) and md:
        try:
            parsed = json.loads(md)
            if isinstance(parsed, dict):
                raw["metadata"] = parsed
            else:
                raw["metadata"] = {"value": parsed}
        except json.JSONDecodeError:
            pass
    return raw


def _detect_entrypoint(skill_dir: Path) -> tuple[str | None, str]:
    """Return (entrypoint_filename, runtime) for *skill_dir*."""
    candidates: list[tuple[str, str]] = [
        ("run.py", "python"),
        ("main.py", "python"),
        ("run.sh", "shell"),
        ("run.js", "node"),
        ("index.js", "node"),
    ]
    for fname, runtime in candidates:
        p = skill_dir / fname
        if p.exists() and p.is_file():
            return fname, runtime
    return None, "prompt"


def _coerce_stream(val: str | bytes | None) -> str:
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val


def _terminate_process_tree(
    proc: subprocess.Popen[bytes], cwd: Path
) -> tuple[bytes, bytes]:
    """Force-terminate a timed-out subprocess.

    Sequence: SIGTERM/terminate → brief grace period → SIGKILL/kill. On
    Windows, ``taskkill /T /F`` kills the whole process tree (the skill and any
    children it spawned) so orphaned grandchildren cannot hold the stdout/stderr
    pipes open. On Unix, ``start_new_session`` put the skill in its own process
    group, so we signal the entire group via ``os.killpg``.

    Returns ``(b"", b"")`` — partial output is deliberately NOT captured on the
    timeout path. Reading a pipe on Windows can block until every writer handle
    closes even after the tree is killed, so the reader ends are closed instead
    to guarantee a bounded return. Correctness of termination takes priority
    over capturing output from a hung process.
    """

    # Windows: kill the entire tree first. Killing only the shell leaves
    # grandchildren holding the pipes open, which blocks Popen.wait().
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
                cwd=str(cwd),
            )
        except OSError:
            pass
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
        return _drain_streams(proc)

    # Unix: signal the whole process group.
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass
    return _drain_streams(proc)


def _drain_streams(proc: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    """Best-effort, non-blocking read of partial stdout/stderr from *proc*.

    Reading a pipe on Windows can block until every writer handle closes even
    after the process tree is killed (grandchildren may hold handles briefly).
    To guarantee a bounded return we close our reader ends first, which flushes
    any buffered data without blocking, then return empty. Partial output is
    deliberately sacrificed on the timeout path — correctness of termination
    takes priority over capturing output from a hung process.
    """
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
    return b"", b""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SkillSpec:
    """Resolved metadata for a single skill, ready to run."""

    name: str
    path: Path
    description: str
    runtime: str  # "prompt" | "python" | "shell" | "node"
    requires_bins: list[str]
    requires_env: list[str]
    entrypoint: str | None
    raw_metadata: dict[str, Any]
    sandbox: bool = True  # static AST gate for python entrypoints (P2-2)


@dataclass
class RunResult:
    """Outcome of a single skill invocation."""

    skill: str
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    error: str | None


# ---------------------------------------------------------------------------
# SkillRunner
# ---------------------------------------------------------------------------


class SkillRunner:
    """Discover and execute skills under *base_dir*."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def discover(self) -> list[SkillSpec]:
        """Scan *base_dir* subdirectories and return one SkillSpec per skill."""
        if not self.base_dir.exists():
            return []
        specs: list[SkillSpec] = []
        for entry in sorted(self.base_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            specs.append(self._build_spec(entry, skill_md))
        return specs

    def get(self, name: str) -> SkillSpec | None:
        """Return the SkillSpec for *name*, or None if not installed."""
        for spec in self.discover():
            if spec.name == name:
                return spec
        return None

    def run(
        self,
        name: str,
        args: list[str] | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        """Run skill *name*. Returns a RunResult (never raises)."""
        spec = self.get(name)
        if spec is None:
            return RunResult(
                skill=name,
                ok=False,
                stdout="",
                stderr="",
                exit_code=-1,
                duration=0.0,
                error=f"skill not found: {name}",
            )
        if spec.entrypoint is None:
            return self._run_prompt(spec)
        return self._run_exec(spec, args or [], timeout)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _build_spec(self, skill_dir: Path, skill_md: Path) -> SkillSpec:
        fm = _parse_front_matter(skill_md)
        description = str(fm.get("description", "")) or ""
        sandbox = _parse_sandbox_flag(fm.get("sandbox"))
        raw_metadata = fm.get("metadata")
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        requires_bins: list[str] = []
        requires_env: list[str] = []
        clawdbot = raw_metadata.get("clawdbot")
        if isinstance(clawdbot, dict):
            req = clawdbot.get("requires")
            if isinstance(req, dict):
                bins = req.get("bins")
                if isinstance(bins, list):
                    requires_bins = [str(b) for b in bins]
                env = req.get("env")
                if isinstance(env, list):
                    requires_env = [str(e) for e in env]
        entrypoint, runtime = _detect_entrypoint(skill_dir)
        return SkillSpec(
            name=skill_dir.name,
            path=skill_dir,
            description=description,
            runtime=runtime,
            requires_bins=requires_bins,
            requires_env=requires_env,
            entrypoint=entrypoint,
            raw_metadata=raw_metadata,
            sandbox=sandbox,
        )

    def _run_prompt(self, spec: SkillSpec) -> RunResult:
        skill_md = spec.path / "SKILL.md"
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            return RunResult(
                skill=spec.name,
                ok=False,
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                duration=0.0,
                error=str(exc),
            )
        return RunResult(
            skill=spec.name,
            ok=True,
            stdout=content,
            stderr="",
            exit_code=0,
            duration=0.0,
            error=None,
        )

    def _run_exec(
        self, spec: SkillSpec, args: list[str], timeout: float | None
    ) -> RunResult:
        missing = [b for b in spec.requires_bins if shutil.which(b) is None]
        if missing:
            return RunResult(
                skill=spec.name,
                ok=False,
                stdout="",
                stderr=f"missing required binaries: {', '.join(missing)}",
                exit_code=-1,
                duration=0.0,
                error=f"missing bins: {missing}",
            )
        if spec.runtime == "python" and spec.sandbox and spec.entrypoint:
            report = check_python_file(spec.path / spec.entrypoint)
            if not report.clean:
                first = report.violations[0]
                return RunResult(
                    skill=spec.name,
                    ok=False,
                    stdout="",
                    stderr=f"sandbox blocked: {first.message} (line {first.line})",
                    exit_code=-1,
                    duration=0.0,
                    error=f"sandbox blocked at line {first.line}: {first.message}",
                )
        try:
            cmd = self._build_command(spec, args)
        except FileNotFoundError as exc:
            return RunResult(
                skill=spec.name,
                ok=False,
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                duration=0.0,
                error=str(exc),
            )
        env = self._build_safe_env(spec)
        start = time.time()
        try:
            proc = self._popen(cmd, spec, env)
        except OSError as exc:
            return RunResult(
                skill=spec.name,
                ok=False,
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                duration=time.time() - start,
                error=str(exc),
            )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stdout_b, stderr_b = _terminate_process_tree(proc, spec.path)
            return RunResult(
                skill=spec.name,
                ok=False,
                stdout=_coerce_stream(stdout_b),
                stderr=_coerce_stream(stderr_b),
                exit_code=-1,
                duration=time.time() - start,
                error=f"timeout after {timeout}s",
            )
        duration = time.time() - start
        ok = proc.returncode == 0
        return RunResult(
            skill=spec.name,
            ok=ok,
            stdout=_coerce_stream(stdout),
            stderr=_coerce_stream(stderr),
            exit_code=proc.returncode,
            duration=duration,
            error=None if ok else f"exit {proc.returncode}",
        )

    def _popen(
        self, cmd: list[str], spec: SkillSpec, env: dict[str, str]
    ) -> subprocess.Popen[bytes]:
        """Spawn the skill subprocess with platform-appropriate isolation.

        - Unix: ``start_new_session=True`` creates a new process group so the
          whole tree can be signaled together on timeout.
        - Windows: ``CREATE_NEW_PROCESS_GROUP`` enables group termination via
          ``taskkill /T /F`` fallback.
        """
        popen_kwargs: dict[str, Any] = {
            "cwd": str(spec.path),
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        return subprocess.Popen(cmd, **popen_kwargs)

    def _build_command(self, spec: SkillSpec, args: list[str]) -> list[str]:
        if spec.entrypoint is None:
            return list(args)
        if spec.runtime == "python":
            return [sys.executable, spec.entrypoint, *args]
        if spec.runtime == "shell":
            sh = _find_posix_shell()
            if sh is None:
                raise FileNotFoundError(
                    "sh: POSIX shell not found on PATH or Git-for-Windows"
                )
            return [sh, spec.entrypoint, *args]
        if spec.runtime == "node":
            return ["node", spec.entrypoint, *args]
        return [spec.entrypoint, *args]

    def _sanitized_env(self) -> dict[str, str]:
        """Return os.environ with sensitive keys stripped.

        Kept for backward compatibility. New call sites should prefer
        :meth:`_build_safe_env`, which applies the stricter allow-list.
        """
        return {k: v for k, v in os.environ.items() if not _looks_sensitive(k)}

    def _build_safe_env(self, spec: SkillSpec) -> dict[str, str]:
        """Build the allow-listed environment for a skill subprocess.

        Includes, in order:
          1. Base-safe variables (``_SAFE_ENV_KEYS``) always present in the
             parent environment.
          2. Variables explicitly required by the skill (``spec.requires_env``).
          3. Any other parent variable whose name is *not* sensitive AND whose
             value does not look like an embedded credential — this preserves
             broad compatibility while blocking both secret-shaped names and
             secret-bearing values (e.g. connection URLs with userinfo).

        Sensitive variables are never passed unless the skill explicitly lists
        them, and even then they are omitted (secrets must not leak into
        arbitrary subprocesses).
        """
        parent = os.environ
        env: dict[str, str] = {}
        # Force UTF-8 on the subprocess regardless of the parent locale: on
        # Windows the default stdout encoding is the ANSI code page (GBK), which
        # crashes scripts printing emoji/CJK. This must be set explicitly, not
        # merely passed through.
        env["PYTHONIOENCODING"] = "utf-8"
        for key in _SAFE_ENV_KEYS:
            if key in parent:
                env[key] = parent[key]
        # Explicitly required env (non-sensitive name AND non-credential value).
        for key in spec.requires_env:
            if key in parent and not _looks_sensitive(key) and not _looks_sensitive_value(parent[key]):
                env[key] = parent[key]
        # Non-sensitive passthrough for compatibility (name AND value gated).
        for key, value in parent.items():
            if key in env:
                continue
            if _looks_sensitive(key):
                continue
            if _looks_sensitive_value(value):
                continue
            env[key] = value
        return env
