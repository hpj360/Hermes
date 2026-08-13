"""Static skill sandbox: AST-based safety gate for Python skill entrypoints.

P2-2 originally proposed RestrictedPython (third-party) or OS-level isolation
(Job Object / chroot). Both violate the zero-dependency baseline: the former is
a third-party package, the latter needs privileged OS calls. This module instead
implements a *best-effort static* gate over a skill entrypoint's abstract syntax
tree using only the stdlib ``ast`` module, and refuses to run code that uses
known-dangerous constructs.

Scope and trust model
---------------------
This is a defense-in-depth layer, **not** a security boundary. The real boundary
remains the subprocess isolation + env allow-list from P0-3 (``skill_runner``).
Static analysis cannot catch everything (e.g. ``getattr(os, "system")`` or
obfuscated imports), so the gate is deliberately conservative: it only flags
patterns it can actually see, and treats every flag as a hard refusal. Shell and
Node entrypoints are *not* statically analysed here (no stdlib AST for those
languages); they rely on the env/process isolation alone.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Deny lists
# ---------------------------------------------------------------------------

# Modules whose import *alone* grants a capability the sandbox must deny. The
# check runs on the top-level package name so ``import subprocess`` and
# ``from subprocess import run`` are both caught.
DANGEROUS_IMPORTS = frozenset(
    {
        "subprocess",
        "socket",
        "ctypes",
        "importlib",
        "pickle",
        "marshal",
        "ftplib",
        "http.client",
        "http.server",
        "smtplib",
        "smtpd",
        "telnetlib",
        "pty",
        "popen2",
        "urllib.request",
        "urllib2",
        "requests",
        "httpx",
        "aiohttp",
        "paramiko",
        "fabric",
        "selenium",
        "pyautogui",
        "webbrowser",
        "xmlrpc",
        "multiprocessing",
        "asyncio.subprocess",
    }
)

# Bare call names that are always dangerous regardless of how they are bound.
DANGEROUS_BARE_CALLS = frozenset(
    {"eval", "exec", "compile", "__import__", "globals", "locals", "breakpoint"}
)

# ``(module, attribute)`` pairs that are dangerous to call on a name bound to a
# module alias (``os.system``, ``shutil.rmtree``, ...).
DANGEROUS_ATTRIBUTE_CALLS = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("os", "popen2"),
        ("os", "popen3"),
        ("os", "popen4"),
        ("os", "spawnl"),
        ("os", "spawnle"),
        ("os", "spawnlp"),
        ("os", "spawnlpe"),
        ("os", "spawnv"),
        ("os", "spawnve"),
        ("os", "spawnvp"),
        ("os", "spawnvpe"),
        ("os", "execl"),
        ("os", "execle"),
        ("os", "execlp"),
        ("os", "execlpe"),
        ("os", "execv"),
        ("os", "execve"),
        ("os", "execvp"),
        ("os", "execvpe"),
        ("os", "remove"),
        ("os", "unlink"),
        ("os", "rmdir"),
        ("os", "removedirs"),
        ("os", "chmod"),
        ("os", "chown"),
        ("os", "chroot"),
        ("os", "kill"),
        ("os", "killpg"),
        ("os", "fork"),
        ("os", "forkpty"),
        ("os", "setuid"),
        ("os", "setgid"),
        ("os", "setpgid"),
        ("os", "abort"),
        ("shutil", "rmtree"),
        ("sys", "settrace"),
        ("sys", "setprofile"),
    }
)

# Dunder attribute access that escapes the sandbox by reaching into
# object/code/globals internals.
DANGEROUS_DUNDERS = frozenset(
    {
        "__class__",
        "__bases__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__func__",
        "__self__",
        "__reduce__",
        "__reduce_ex__",
        "__getattribute__",
    }
)

# ``open`` mode characters that imply writing / modifying files.
_WRITE_MODE_CHARS = frozenset("wax+")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class SandboxViolation:
    """A single static-sandbox finding."""

    line: int
    message: str


@dataclass
class SandboxReport:
    """Result of analysing a skill entrypoint source file."""

    clean: bool
    violations: list[SandboxViolation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _open_writes(node: ast.Call) -> bool:
    """Return True if an ``open``/``*.open`` call uses a write-ish mode."""
    mode = ""
    if len(node.args) >= 2:
        arg = node.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            mode = arg.value
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            if isinstance(kw.value.value, str):
                mode = kw.value.value
    return any(c in _WRITE_MODE_CHARS for c in mode)


def _check_call(node: ast.Call) -> SandboxViolation | None:
    func = node.func
    if isinstance(func, ast.Name):
        name = func.id
        if name in DANGEROUS_BARE_CALLS:
            return SandboxViolation(node.lineno, f"call to forbidden builtin '{name}'")
        if name == "open" and _open_writes(node):
            return SandboxViolation(node.lineno, "open() with a write/append mode")
        return None

    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name) and (base.id, func.attr) in DANGEROUS_ATTRIBUTE_CALLS:
            return SandboxViolation(
                node.lineno, f"call to forbidden '{base.id}.{func.attr}'"
            )
        if func.attr == "open" and _open_writes(node):
            return SandboxViolation(node.lineno, "open() with a write/append mode")
        return None

    return None


def analyze_python_source(source: str) -> list[SandboxViolation]:
    """Analyse Python *source* and return any sandbox violations.

    An empty list means the source passed the static gate. A ``SyntaxError`` is
    reported as a single violation (unparseable code is refused too).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [SandboxViolation(exc.lineno or 0, f"syntax error: {exc.msg}")]

    violations: list[SandboxViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in DANGEROUS_IMPORTS:
                    violations.append(
                        SandboxViolation(
                            node.lineno, f"import of forbidden module '{alias.name}'"
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in DANGEROUS_IMPORTS:
                violations.append(
                    SandboxViolation(
                        node.lineno, f"import from forbidden module '{node.module}'"
                    )
                )
        elif isinstance(node, ast.Call):
            violation = _check_call(node)
            if violation is not None:
                violations.append(violation)
        elif isinstance(node, ast.Attribute):
            if node.attr in DANGEROUS_DUNDERS:
                violations.append(
                    SandboxViolation(
                        node.lineno, f"access to dunder attribute '{node.attr}'"
                    )
                )
    return violations


def check_python_file(path: Path) -> SandboxReport:
    """Analyse the Python source at *path* and return a :class:`SandboxReport`.

    A missing/unreadable file degrades to ``clean=True`` so the caller lets the
    subprocess surface the real I/O error (the sandbox must not mask it).
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return SandboxReport(clean=True, violations=[])
    violations = analyze_python_source(source)
    return SandboxReport(clean=not violations, violations=violations)
