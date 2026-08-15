"""Skill marketplace: git/HTTP-based distribution with a zero-dependency catalog.

P3-4 originally assumed an online registry / distribution service. Instead the
registry is treated as a plain catalog file plus standard git/HTTP transport, so
no custom service is required:

* **registry** — ``skills/registry.json`` (vendored in-repo) plus an optional
  remote catalog fetched over stdlib ``urllib`` (``HERMES_SKILL_REGISTRY`` URL).
* **install** — resolve a name/source to a git URL, local path or zip archive,
  then copy the skill directory into ``skills/``.
* **pack** — bundle a skill into a versioned zip (stdlib ``zipfile``).

Zero-runtime-dependency constraint: ``git`` is invoked as a subprocess (it is a
dev tool already required by the repo's sync scripts, not a Python dependency);
HTTP uses stdlib ``urllib``; archives use stdlib ``zipfile``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes.config import get_settings
from hermes.skills import load_skill_manifest, skills_dir

# A skill name is a single path component: letters/digits plus ``._-``.
# Rejects path separators, ``..``, drive letters, and anything that could
# escape the skills directory via ``target = skills_dir() / name`` or
# ``shutil.rmtree(target)``.
_SKILL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@dataclass
class MarketResult:
    """Outcome of a marketplace operation (install / pack)."""

    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def registry_file() -> Path:
    """Return the vendored registry catalog path (``skills/registry.json``)."""
    return skills_dir() / "registry.json"


def _normalize_registry(data: Any) -> dict[str, dict[str, str]]:
    """Coerce an arbitrary decoded registry payload into ``{name: {...}}``."""
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for name, entry in data.items():
        if isinstance(entry, dict):
            result[str(name)] = {str(k): str(v) for k, v in entry.items()}
    return result


def load_registry() -> dict[str, dict[str, str]]:
    """Load the vendored ``skills/registry.json`` catalog (empty on error)."""
    f = registry_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _normalize_registry(data)


def fetch_registry(url: str, timeout: float = 10.0) -> dict[str, dict[str, str]]:
    """Fetch and parse a remote registry catalog over stdlib ``urllib``."""
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "hermes-skill-market"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return _normalize_registry(payload)


def remote_registry_url() -> str:
    """Return the configured remote registry URL (``HERMES_SKILL_REGISTRY``)."""
    return get_settings().hermes_skill_registry.strip()


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------


def _is_git_source(source: str) -> bool:
    s = source.strip()
    return s.startswith(("git@", "ssh://", "git://", "git+ssh://")) or (
        s.startswith(("http://", "https://")) and s.endswith(".git")
    )


def _is_zip_source(source: str) -> bool:
    return source.strip().lower().endswith(".zip")


def _is_http(source: str) -> bool:
    return source.strip().startswith(("http://", "https://"))


def _is_skill_dir(path: Path) -> bool:
    return (path / "SKILL.md").exists() or (path / "manifest.yaml").exists()


# ---------------------------------------------------------------------------
# Acquire a skill from a source (returns a staging directory root)
# ---------------------------------------------------------------------------


def _extract_zip(archive: Path, workdir: Path) -> Path:
    extract_dir = workdir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    _safe_extract_zip(archive, extract_dir)
    return extract_dir


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "hermes-skill-market"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp, dest.open("wb") as fp:
        shutil.copyfileobj(resp, fp)


def _git_clone(url: str, workdir: Path) -> Path:
    clone_dir = workdir / "clone"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(clone_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise OSError("git not found on PATH; install git to use git sources") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise OSError(f"git clone failed: {detail or exc}") from exc
    return clone_dir


def _acquire(source: str, workdir: Path) -> Path:
    """Fetch *source* into *workdir* and return the staging root directory."""
    s = source.strip()
    if os.path.isdir(s):
        return Path(s)
    if _is_zip_source(s) and os.path.isfile(s):
        return _extract_zip(Path(s), workdir)
    if _is_zip_source(s) and _is_http(s):
        archive = workdir / "download.zip"
        _download(s, archive)
        return _extract_zip(archive, workdir)
    if _is_git_source(s) or _is_http(s):
        return _git_clone(s, workdir)
    raise ValueError(f"unsupported skill source: {source}")


def _locate_skill_dir(root: Path, name: str) -> Path | None:
    """Find the actual skill directory inside a staging *root*.

    Accepts the skill living at the repository root, at a top-level ``<name>/``
    directory, or (for an already-flat archive) as the root itself.
    """
    if _is_skill_dir(root):
        return root
    candidate = root / name
    if _is_skill_dir(candidate):
        return candidate
    return None


def validate_skill_name(name: str) -> str | None:
    """Return an error message when *name* is not a safe single path component.

    Return ``None`` when the name is safe. A safe name is non-empty, contains
    only ``[A-Za-z0-9._-]``, does not begin with a dot (hidden files), and
    never equals ``.`` or ``..``. This guards both the ``skills_dir()/name``
    join and the ``shutil.rmtree(target)`` call in :func:`install_skill`.
    """
    if not name or not isinstance(name, str):
        return "skill name must be a non-empty string"
    if not _SKILL_NAME_RE.match(name):
        return (
            f"invalid skill name {name!r}: only letters, digits, '.', '_', '-', and "
            "a single path component are allowed"
        )
    if name in (".", "..") or name.startswith("."):
        return f"invalid skill name {name!r}: hidden or parent-directory name"
    return None


def _safe_extract_zip(archive: Path, extract_dir: Path) -> None:
    """Extract *archive* into *extract_dir*, rejecting path-traversal entries.

    This is a zip-slip guard: every entry's resolved target must stay inside
    ``extract_dir``. Symlink entries are skipped entirely (a symlink can point
    outside the extraction sandbox). Duplicate names and directories are
    handled consistently with an ordinary ``extractall``.
    """
    extract_dir = extract_dir.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            # Skip directory entries and symlinks; regular files only.
            if member.is_dir():
                continue
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:  # symlink
                continue
            target = (extract_dir / member.filename).resolve()
            if extract_dir != target and extract_dir not in target.parents:
                raise OSError(f"zip entry escapes extraction dir: {member.filename!r}")
            # Defend against a prior file entry creating the dir for a later
            # path, and against a crafted dir entry sitting where a file must go.
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install_skill(
    name: str,
    *,
    source: str | None = None,
    dest: Path | None = None,
    force: bool = False,
) -> MarketResult:
    """Install skill *name* into ``skills/``.

    Resolution order: an explicit ``source`` (git URL / local path / zip), else
    the vendored registry, else the remote registry (if configured).
    """
    name_err = validate_skill_name(name)
    if name_err is not None:
        return MarketResult(False, name_err)

    target = (dest or skills_dir()) / name
    # Defense-in-depth: even with a validated name, never let the resolved
    # target escape its parent (guards an unexpected ``dest`` or a symlinked
    # skills dir).
    target_parent = target.parent.resolve()
    resolved = target.resolve()
    if resolved != target_parent / name and target_parent not in resolved.parents:
        return MarketResult(False, f"skill target escapes skills directory: {name!r}")

    resolved_from = "source"

    src = source
    if src is None:
        entry = load_registry().get(name)
        if entry is not None:
            resolved_from = "registry"
            src = entry.get("source", "")
        else:
            url = remote_registry_url()
            if url:
                try:
                    entry = fetch_registry(url).get(name)
                except (urllib.error.URLError, OSError, json.JSONDecodeError):
                    entry = None
                if entry is not None:
                    resolved_from = "remote-registry"
                    src = entry.get("source", "")
        if not src:
            return MarketResult(False, f"skill '{name}' not found in any registry")

    if target.exists():
        if not force:
            return MarketResult(
                False, f"skill '{name}' already installed (use --force to overwrite)"
            )
        shutil.rmtree(target)

    with tempfile.TemporaryDirectory(prefix="hermes-skill-") as tmp:
        try:
            root = _acquire(src, Path(tmp))
        except (OSError, ValueError) as exc:
            return MarketResult(False, f"failed to acquire '{name}': {exc}")
        skill_dir = _locate_skill_dir(root, name)
        if skill_dir is None:
            return MarketResult(
                False, f"source did not contain a skill named '{name}' (missing SKILL.md)"
            )
        try:
            shutil.copytree(skill_dir, target)
        except OSError as exc:
            return MarketResult(False, f"failed to copy skill: {exc}")

    return MarketResult(
        True,
        f"installed skill '{name}'",
        {"name": name, "path": str(target), "resolved_from": resolved_from},
    )


def pack_skill(name: str, *, output_dir: Path | None = None) -> MarketResult:
    """Pack skill *name* into ``<name>-<version>.zip`` (stdlib ``zipfile``)."""
    skill_path = skills_dir() / name
    if not skill_path.is_dir():
        return MarketResult(False, f"skill '{name}' not found")

    manifest = load_skill_manifest(name)
    version = (manifest.version if manifest else "").strip()
    version = re.sub(r"[^0-9A-Za-z._-]", "-", version) or "0.0.0"

    out = output_dir or get_settings().hermes_cache_dir
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{name}-{version}.zip"
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(skill_path.rglob("*")):
                if p.is_file():
                    zf.write(p, arcname=f"{name}/{p.relative_to(skill_path).as_posix()}")
    except OSError as exc:
        return MarketResult(False, f"failed to pack '{name}': {exc}")

    return MarketResult(
        True,
        f"packed skill '{name}'",
        {"name": name, "version": version, "archive": str(archive)},
    )


def list_registry() -> dict[str, dict[str, str]]:
    """Merge the vendored catalog with the remote catalog (if configured)."""
    merged = load_registry()
    url = remote_registry_url()
    if url:
        try:
            remote = fetch_registry(url)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            remote = {}
        for name, entry in remote.items():
            merged.setdefault(name, entry)
    return merged
