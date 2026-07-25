"""Phase 3.6 cross-project asset synchronization.

One-way (source -> target) propagation of three asset classes between
project runtimes managed by ``Router``:

- **skills**: copy each source skill's ``SKILL.md`` plus its detected
  entrypoint file (``run.py`` / ``main.py`` / ``run.sh`` / ``run.js`` /
  ``index.js``) into the target project's ``skills_dir``.
- **memory**: merge L1 facts (source overwrites target same-key via
  ``MemoryService.remember_fact``) and append L2 episodes that the target
  does not already have (deduplicated by ``Episode.id``).
- **profile**: shallow-merge the project-level ``profile.json`` top-level
  fields, with source values overriding target values.

Only the Python standard library is used; no new dependencies.

Design notes
------------
- ``AssetSync`` is stateless beyond its ``Router`` reference; the router
  caches ``ProjectRuntime`` instances, so repeated syncs reuse the same
  runner/memory objects.
- Per-target errors are collected into ``SyncResult.errors`` rather than
  aborting the whole batch, but a missing source or target project id
  raises ``NotFoundError`` immediately (validated upfront).
- ``scope="all"`` runs skills, memory, and profile in that order for
  each target before moving on to the next target.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes.workbench.errors import ValidationError
from hermes.workbench.persistence import atomic_write_json, safe_read_json

__all__ = ["AssetSync", "SyncResult"]

_VALID_SCOPES = frozenset({"skills", "memory", "profile", "all"})


@dataclass
class SyncResult:
    """Outcome of a single ``AssetSync.sync()`` call.

    Fields:
    - ok: True if no per-target errors occurred.
    - scope: one of "skills" | "memory" | "profile" | "all".
    - source: the source project id.
    - targets: target project ids that were synced.
    - synced_count: total number of items copied/merged across all targets.
    - errors: human-readable error strings, one per failure.
    """

    ok: bool
    scope: str
    source: str
    targets: list[str] = field(default_factory=list)
    synced_count: int = 0
    errors: list[str] = field(default_factory=list)


class AssetSync:
    """Cross-project asset sync engine (one-way: source -> targets).

    The router's ``resolve(project_id)`` is the single source of truth for
    project existence; a missing source or any missing target raises
    ``NotFoundError`` before any files are touched.
    """

    def __init__(self, router: Any) -> None:
        self._router = router

    def sync(self, source: str, targets: list[str], scope: str) -> SyncResult:
        """Run a one-way sync from *source* to each id in *targets*.

        Raises ``ValidationError`` if *scope* is not one of the supported
        scopes, and ``NotFoundError`` if *source* or any target project id
        cannot be resolved by the router.
        """
        if scope not in _VALID_SCOPES:
            raise ValidationError(
                f"invalid scope {scope!r}; expected one of {sorted(_VALID_SCOPES)}"
            )

        # Resolve source first — raises NotFoundError if missing.
        src_rt = self._router.resolve(source)
        # Validate every target upfront so a missing id aborts before any
        # partial work is done. Router caches runtimes, so the second
        # resolution in the loop is cheap.
        resolved_targets: list[tuple[str, Any]] = []
        for tgt_id in targets:
            tgt_rt = self._router.resolve(tgt_id)  # raises NotFoundError
            resolved_targets.append((tgt_id, tgt_rt))

        errors: list[str] = []
        synced = 0
        for tgt_id, tgt_rt in resolved_targets:
            try:
                if scope in ("skills", "all"):
                    n, errs = self._sync_skills(src_rt, tgt_rt)
                    synced += n
                    errors.extend(f"target {tgt_id}: {e}" for e in errs)
                if scope in ("memory", "all"):
                    n, errs = self._sync_memory(src_rt, tgt_rt)
                    synced += n
                    errors.extend(f"target {tgt_id}: {e}" for e in errs)
                if scope in ("profile", "all"):
                    n, errs = self._sync_profile(src_rt, tgt_rt)
                    synced += n
                    errors.extend(f"target {tgt_id}: {e}" for e in errs)
            except Exception as e:  # noqa: BLE001 — boundary: keep going
                errors.append(f"target {tgt_id}: unexpected error: {e}")

        return SyncResult(
            ok=len(errors) == 0,
            scope=scope,
            source=source,
            targets=[tgt_id for tgt_id, _ in resolved_targets],
            synced_count=synced,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def _sync_skills(self, src_rt: Any, tgt_rt: Any) -> tuple[int, list[str]]:
        """Copy SKILL.md + entrypoint for each discovered source skill."""
        errors: list[str] = []
        synced = 0

        src_skills_dir = self._skills_dir_for(src_rt)
        tgt_skills_dir = self._skills_dir_for(tgt_rt)
        if src_skills_dir is None:
            return 0, ["source has no skills_dir configured"]
        if tgt_skills_dir is None:
            return 0, ["target has no skills_dir configured"]

        tgt_skills_dir.mkdir(parents=True, exist_ok=True)

        try:
            specs = src_rt.runner().discover()
        except Exception as e:  # noqa: BLE001
            return 0, [f"runner discover failed: {e}"]

        for spec in specs:
            skill_name = spec.name
            src_skill_dir = Path(spec.path)
            tgt_skill_dir = tgt_skills_dir / skill_name
            tgt_skill_dir.mkdir(parents=True, exist_ok=True)

            # Always copy SKILL.md if present.
            skill_md = src_skill_dir / "SKILL.md"
            if skill_md.exists():
                try:
                    shutil.copy2(skill_md, tgt_skill_dir / "SKILL.md")
                    synced += 1
                except OSError as e:
                    errors.append(f"skill {skill_name}: SKILL.md copy failed: {e}")
            else:
                # Without SKILL.md the target skill is unusable; record it.
                errors.append(f"skill {skill_name}: missing SKILL.md in source")

            # Copy the detected entrypoint file (if any).
            entrypoint = spec.entrypoint
            if entrypoint:
                src_entry = src_skill_dir / entrypoint
                if src_entry.exists():
                    try:
                        shutil.copy2(src_entry, tgt_skill_dir / entrypoint)
                        synced += 1
                    except OSError as e:
                        errors.append(
                            f"skill {skill_name}: {entrypoint} copy failed: {e}"
                        )

        return synced, errors

    @staticmethod
    def _skills_dir_for(rt: Any) -> Path | None:
        skills_dir = getattr(rt.conn, "skills_dir", None)
        return Path(skills_dir) if skills_dir else None

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------
    def _sync_memory(self, src_rt: Any, tgt_rt: Any) -> tuple[int, list[str]]:
        """Merge L1 facts (source overwrites) and append new L2 episodes."""
        errors: list[str] = []
        synced = 0

        try:
            src_mem = src_rt.memory()
            tgt_mem = tgt_rt.memory()
        except Exception as e:  # noqa: BLE001
            return 0, [f"memory service init failed: {e}"]

        # L1 facts: source overwrites target same-key.
        try:
            facts = src_mem.list_facts()
        except Exception as e:  # noqa: BLE001
            errors.append(f"src list_facts failed: {e}")
            facts = []
        for fact in facts:
            key = fact.get("key")
            value = fact.get("value")
            if key is None:
                continue
            try:
                tgt_mem.remember_fact(key, value)
                synced += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"fact {key!r}: remember failed: {e}")

        # L2 episodes: append only those whose id is not already in target.
        try:
            src_episodes = src_mem.list_episodes(limit=10**9)
        except Exception as e:  # noqa: BLE001
            errors.append(f"src list_episodes failed: {e}")
            src_episodes = []
        try:
            tgt_episodes = tgt_mem.list_episodes(limit=10**9)
        except Exception as e:  # noqa: BLE001
            errors.append(f"tgt list_episodes failed: {e}")
            tgt_episodes = []

        existing_ids = {ep.id for ep in tgt_episodes}
        for ep in src_episodes:
            if ep.id in existing_ids:
                continue
            try:
                tgt_mem.record_episode(ep)
                synced += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"episode {ep.id}: record failed: {e}")

        return synced, errors

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    def _sync_profile(self, src_rt: Any, tgt_rt: Any) -> tuple[int, list[str]]:
        """Shallow-merge source profile.json over target (source wins)."""
        errors: list[str] = []

        src_profile_path = Path(src_rt.conn.state_dir) / "profile.json"
        tgt_profile_path = Path(tgt_rt.conn.state_dir) / "profile.json"

        # No source profile → nothing to sync.
        if not src_profile_path.exists():
            return 0, []

        src_profile = safe_read_json(src_profile_path, default={})
        if not isinstance(src_profile, dict):
            errors.append("source profile.json is not a JSON object")
            return 0, errors

        tgt_profile = safe_read_json(tgt_profile_path, default={})
        if not isinstance(tgt_profile, dict):
            tgt_profile = {}

        merged = {**tgt_profile, **src_profile}
        try:
            atomic_write_json(tgt_profile_path, merged)
        except OSError as e:
            errors.append(f"profile write failed: {e}")
            return 0, errors

        return 1, errors
