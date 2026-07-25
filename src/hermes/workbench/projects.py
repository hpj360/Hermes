"""Phase 3.2 cross-project routing.

Manages multiple project connections (local/github/api) and provides a Router
that resolves a job's ``target_project`` to the correct ``ProjectRuntime``.
Each runtime bundles a project-scoped ``SkillRunner`` / ``MemoryService`` /
``AgentLoop`` / ``TaskScheduler`` so jobs targeting different projects never
share state.

Concurrency limiting: ``Router.try_acquire`` / ``release`` enforce per-project
``max_concurrent`` to prevent one project from exhausting the worker pool.
"""

from __future__ import annotations

import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes.workbench.errors import NotFoundError, StateError
from hermes.workbench.persistence import atomic_write_json, safe_read_json

__all__ = [
    "ProjectConnection",
    "ProjectRegistry",
    "ProjectRuntime",
    "Router",
]


# ---------------------------------------------------------------------------
# ProjectConnection
# ---------------------------------------------------------------------------


@dataclass
class ProjectConnection:
    """A registered project connection (local/github/api)."""

    id: str
    name: str
    project_type: str  # "local" | "github" | "api"
    state_dir: str
    skills_dir: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    max_concurrent: int = 1
    health: str = "unknown"  # "connected" | "disconnected" | "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "project_type": self.project_type,
            "state_dir": self.state_dir,
            "skills_dir": self.skills_dir,
            "config": self.config,
            "max_concurrent": self.max_concurrent,
            "health": self.health,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectConnection":
        return cls(
            id=data["id"],
            name=data["name"],
            project_type=data["project_type"],
            state_dir=data["state_dir"],
            skills_dir=data.get("skills_dir"),
            config=dict(data.get("config", {})),
            max_concurrent=int(data.get("max_concurrent", 1)),
            health=data.get("health", "unknown"),
        )


# ---------------------------------------------------------------------------
# ProjectRegistry
# ---------------------------------------------------------------------------


class ProjectRegistry:
    """Manages ProjectConnection records, persisted to ``projects.json``.

    The ``default`` project always exists and points to the global
    ``hermes_state_dir``; it cannot be removed.
    """

    def __init__(self, state_dir: Path | str) -> None:
        from hermes.config import get_settings

        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._state_dir / "projects.json"
        self._lock = threading.Lock()
        self._projects: dict[str, dict[str, Any]] = self._load()
        # Ensure default project exists
        if "default" not in self._projects:
            global_state = str(get_settings().hermes_state_dir)
            self._projects["default"] = ProjectConnection(
                id="default",
                name="Default",
                project_type="local",
                state_dir=global_state,
            ).to_dict()
            self._save_locked()

    def _load(self) -> dict[str, dict[str, Any]]:
        data = safe_read_json(self._path, default={})
        return data if isinstance(data, dict) else {}

    def _save_locked(self) -> None:
        atomic_write_json(self._path, self._projects)

    def add(
        self,
        name: str,
        project_type: str,
        state_dir: str,
        skills_dir: str | None = None,
        config: dict[str, Any] | None = None,
        max_concurrent: int = 1,
        conn_id: str | None = None,
    ) -> ProjectConnection:
        import uuid

        conn_id = conn_id or f"proj-{uuid.uuid4().hex[:8]}"
        with self._lock:
            if conn_id in self._projects:
                raise StateError(f"project {conn_id} already exists")
            conn = ProjectConnection(
                id=conn_id,
                name=name,
                project_type=project_type,
                state_dir=state_dir,
                skills_dir=skills_dir,
                config=config or {},
                max_concurrent=max_concurrent,
            )
            self._projects[conn_id] = conn.to_dict()
            self._save_locked()
            return conn

    def get(self, conn_id: str) -> ProjectConnection | None:
        with self._lock:
            data = self._projects.get(conn_id)
        return ProjectConnection.from_dict(data) if data else None

    def list(self) -> list[ProjectConnection]:
        with self._lock:
            snapshot = list(self._projects.values())
        return [ProjectConnection.from_dict(d) for d in snapshot]

    def remove(self, conn_id: str) -> bool:
        if conn_id == "default":
            raise StateError("cannot remove default project")
        with self._lock:
            if conn_id not in self._projects:
                return False
            del self._projects[conn_id]
            self._save_locked()
            return True

    def update_health(self, conn_id: str, health: str) -> bool:
        with self._lock:
            if conn_id not in self._projects:
                return False
            self._projects[conn_id]["health"] = health
            self._save_locked()
            return True

    def summary(self) -> dict[str, Any]:
        with self._lock:
            snapshot = list(self._projects.values())
        by_type: dict[str, int] = {}
        for d in snapshot:
            t = d.get("project_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {"total": len(snapshot), "by_type": by_type}

    def ping(self, conn_id: str) -> dict[str, Any]:
        """Health-check a project. Returns {reachable, status, error?}."""
        conn = self.get(conn_id)
        if conn is None:
            return {"reachable": False, "status": "unknown", "error": "project not found"}
        result = self._ping(conn)
        self.update_health(conn_id, result["status"])
        return result

    def _ping(self, conn: ProjectConnection) -> dict[str, Any]:
        if conn.project_type == "local":
            path = Path(conn.state_dir)
            if path.exists() and path.is_dir():
                return {"reachable": True, "status": "connected"}
            return {"reachable": False, "status": "disconnected", "error": "state_dir not found"}
        if conn.project_type == "github":
            return self._ping_github(conn)
        # api or unknown
        return {"reachable": False, "status": "unknown", "error": f"unsupported type {conn.project_type}"}

    def _ping_github(self, conn: ProjectConnection) -> dict[str, Any]:
        url = conn.config.get("url", "")
        token = conn.config.get("token", "")
        if not url:
            return {"reachable": False, "status": "disconnected", "error": "no url configured"}
        # Normalize to API URL
        if url.startswith("github.com/"):
            owner_repo = url[len("github.com/"):]
            api_url = f"https://api.github.com/repos/{owner_repo}"
        elif url.startswith("https://github.com/"):
            owner_repo = url[len("https://github.com/"):]
            api_url = f"https://api.github.com/repos/{owner_repo}"
        else:
            api_url = url
        try:
            req = urllib.request.Request(api_url)
            if token:
                req.add_header("Authorization", f"token {token}")
            req.add_header("Accept", "application/vnd.github+json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return {"reachable": True, "status": "connected"}
                return {"reachable": False, "status": "disconnected", "error": f"HTTP {resp.status}"}
        except Exception as e:  # noqa: BLE001
            return {"reachable": False, "status": "disconnected", "error": str(e)}


# ---------------------------------------------------------------------------
# ProjectRuntime
# ---------------------------------------------------------------------------


class ProjectRuntime:
    """Bundles a project-scoped runner/memory/loop/scheduler.

    Lazily instantiates components on first access and caches them. Each
    project gets its own ``state_dir`` so L1 facts / L2 episodes / tasks are
    isolated from other projects.
    """

    def __init__(self, conn: ProjectConnection) -> None:
        self.conn = conn
        self._runner: Any = None
        self._memory: Any = None
        self._loop: Any = None
        self._scheduler: Any = None
        self._lock = threading.RLock()  # reentrant: scheduler() calls runner()/memory()

    def runner(self) -> Any:
        if self._runner is None:
            with self._lock:
                if self._runner is None:
                    from hermes.skills import skills_dir as _global_skills_dir
                    from hermes.workbench.skill_runner import SkillRunner

                    base_dir = (
                        Path(self.conn.skills_dir)
                        if self.conn.skills_dir
                        else _global_skills_dir()
                    )
                    self._runner = SkillRunner(base_dir=base_dir)
        return self._runner

    def memory(self) -> Any:
        if self._memory is None:
            with self._lock:
                if self._memory is None:
                    from hermes.workbench.memory import MemoryService

                    self._memory = MemoryService(state_dir=Path(self.conn.state_dir))
        return self._memory

    def loop(self) -> Any:
        if self._loop is None:
            with self._lock:
                if self._loop is None:
                    from hermes.workbench.agent_loop import AgentLoop

                    self._loop = AgentLoop(runner=self.runner(), memory=self.memory())
        return self._loop

    def scheduler(self) -> Any:
        if self._scheduler is None:
            with self._lock:
                if self._scheduler is None:
                    from hermes.workbench.cli import TaskScheduler, TaskStore, TaskRegistry

                    store = TaskStore(state_dir=Path(self.conn.state_dir))
                    registry = TaskRegistry()
                    self._scheduler = TaskScheduler(
                        store=store,
                        registry=registry,
                        runner=self.runner(),
                        memory=self.memory(),
                    )
        return self._scheduler


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class Router:
    """Resolves ``target_project`` to a ``ProjectRuntime`` with concurrency limiting.

    - ``resolve(project_id)``: returns the cached ``ProjectRuntime`` (lazy).
    - ``try_acquire(project_id)``: atomically increments in-flight count if
      under ``max_concurrent``, else returns False. Worker must call
      ``release`` after the job finishes.
    """

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry
        self._runtimes: dict[str, ProjectRuntime] = {}
        self._inflight: dict[str, int] = {}
        self._lock = threading.Lock()

    def resolve(self, project_id: str) -> ProjectRuntime:
        conn = self._registry.get(project_id)
        if conn is None:
            raise NotFoundError(f"project not found: {project_id}")
        with self._lock:
            rt = self._runtimes.get(project_id)
            if rt is None:
                rt = ProjectRuntime(conn)
                self._runtimes[project_id] = rt
            return rt

    def try_acquire(self, project_id: str) -> bool:
        with self._lock:
            conn = self._registry.get(project_id)
            if conn is None:
                return False
            current = self._inflight.get(project_id, 0)
            if current >= conn.max_concurrent:
                return False
            self._inflight[project_id] = current + 1
            return True

    def release(self, project_id: str) -> None:
        with self._lock:
            current = self._inflight.get(project_id, 0)
            if current <= 0:
                return
            self._inflight[project_id] = current - 1

    def inflight_count(self, project_id: str) -> int:
        with self._lock:
            return self._inflight.get(project_id, 0)
