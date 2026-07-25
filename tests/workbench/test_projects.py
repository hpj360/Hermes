"""Tests for Phase 3.2 cross-project routing (projects.py).

Covers: ProjectConnection dataclass, ProjectRegistry CRUD + persistence,
ProjectRuntime lazy loading + state_dir isolation, Router resolve +
try_acquire/release concurrency limiting, ping health check.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes.workbench.projects import (
    ProjectConnection,
    ProjectRegistry,
    ProjectRuntime,
    Router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(state_dir=tmp_path)


@pytest.fixture
def local_conn() -> ProjectConnection:
    return ProjectConnection(
        id="proj-a",
        name="Project A",
        project_type="local",
        state_dir="/tmp/proj-a",
        skills_dir=None,
        config={},
    )


# ---------------------------------------------------------------------------
# ProjectConnection
# ---------------------------------------------------------------------------


class TestProjectConnection:
    def test_defaults(self) -> None:
        conn = ProjectConnection(
            id="x",
            name="X",
            project_type="local",
            state_dir="/tmp/x",
        )
        assert conn.skills_dir is None
        assert conn.config == {}
        assert conn.max_concurrent == 1
        assert conn.health == "unknown"

    def test_to_dict_roundtrip(self) -> None:
        conn = ProjectConnection(
            id="proj-a",
            name="A",
            project_type="github",
            state_dir="/tmp/a",
            skills_dir="/tmp/a/skills",
            config={"url": "github.com/o/r", "token": "tok"},
            max_concurrent=3,
            health="connected",
        )
        d = conn.to_dict()
        conn2 = ProjectConnection.from_dict(d)
        assert conn2.id == conn.id
        assert conn2.project_type == "github"
        assert conn2.config["url"] == "github.com/o/r"
        assert conn2.max_concurrent == 3
        assert conn2.health == "connected"


# ---------------------------------------------------------------------------
# ProjectRegistry
# ---------------------------------------------------------------------------


class TestProjectRegistry:
    def test_default_project_exists(self, registry: ProjectRegistry) -> None:
        """default 项目始终存在，指向全局 state_dir。"""
        default = registry.get("default")
        assert default is not None
        assert default.id == "default"
        assert default.project_type == "local"

    def test_add_and_get(self, registry: ProjectRegistry, local_conn: ProjectConnection) -> None:
        added = registry.add(
            name=local_conn.name,
            project_type=local_conn.project_type,
            state_dir=local_conn.state_dir,
            skills_dir=local_conn.skills_dir,
            config=local_conn.config,
            conn_id=local_conn.id,
        )
        assert added.id == "proj-a"
        fetched = registry.get("proj-a")
        assert fetched is not None
        assert fetched.name == "Project A"

    def test_add_duplicate_id_raises(self, registry: ProjectRegistry) -> None:
        registry.add(name="A", project_type="local", state_dir="/tmp/a", conn_id="dup")
        from hermes.workbench.errors import StateError

        with pytest.raises(StateError, match="already exists"):
            registry.add(name="B", project_type="local", state_dir="/tmp/b", conn_id="dup")

    def test_list(self, registry: ProjectRegistry) -> None:
        registry.add(name="A", project_type="local", state_dir="/tmp/a", conn_id="a")
        registry.add(name="B", project_type="local", state_dir="/tmp/b", conn_id="b")
        items = registry.list()
        ids = {p.id for p in items}
        assert {"default", "a", "b"} == ids

    def test_remove(self, registry: ProjectRegistry) -> None:
        registry.add(name="A", project_type="local", state_dir="/tmp/a", conn_id="a")
        assert registry.remove("a") is True
        assert registry.get("a") is None
        assert registry.remove("nonexistent") is False

    def test_cannot_remove_default(self, registry: ProjectRegistry) -> None:
        from hermes.workbench.errors import StateError

        with pytest.raises(StateError, match="cannot remove default"):
            registry.remove("default")

    def test_persistence_across_instances(self, registry: ProjectRegistry, tmp_path: Path) -> None:
        registry.add(name="A", project_type="local", state_dir="/tmp/a", conn_id="a")
        registry2 = ProjectRegistry(state_dir=tmp_path)
        assert registry2.get("a") is not None

    def test_summary(self, registry: ProjectRegistry) -> None:
        registry.add(name="A", project_type="github", state_dir="/tmp/a", conn_id="a")
        summary = registry.summary()
        assert summary["total"] == 2  # default + a
        assert summary["by_type"]["local"] == 1
        assert summary["by_type"]["github"] == 1

    def test_ping_local_success(self, registry: ProjectRegistry, tmp_path: Path) -> None:
        conn = registry.add(
            name="local-proj",
            project_type="local",
            state_dir=str(tmp_path),
            conn_id="local-proj",
        )
        result = registry.ping(conn.id)
        assert result["reachable"] is True
        assert result["status"] == "connected"

    def test_ping_local_missing_dir(self, registry: ProjectRegistry) -> None:
        conn = registry.add(
            name="missing",
            project_type="local",
            state_dir="/nonexistent/path/xyz",
            conn_id="missing",
        )
        result = registry.ping(conn.id)
        assert result["reachable"] is False
        assert result["status"] == "disconnected"

    def test_ping_github_success(self, registry: ProjectRegistry) -> None:
        conn = registry.add(
            name="gh",
            project_type="github",
            state_dir="/tmp/gh",
            config={"url": "github.com/owner/repo", "token": "tok"},
            conn_id="gh",
        )
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
            mock_urlopen.return_value.__enter__.return_value.status = 200
            result = registry.ping(conn.id)
        assert result["reachable"] is True
        assert result["status"] == "connected"

    def test_ping_unknown_type(self, registry: ProjectRegistry) -> None:
        conn = registry.add(
            name="weird",
            project_type="api",
            state_dir="/tmp/api",
            conn_id="weird",
        )
        result = registry.ping(conn.id)
        assert result["reachable"] is False
        assert result["status"] == "unknown"


# ---------------------------------------------------------------------------
# ProjectRuntime
# ---------------------------------------------------------------------------


class TestProjectRuntime:
    def test_lazy_loading(self, tmp_path: Path) -> None:
        conn = ProjectConnection(
            id="x",
            name="X",
            project_type="local",
            state_dir=str(tmp_path),
        )
        runtime = ProjectRuntime(conn)
        # 初始未实例化
        runner = runtime.runner()
        assert runner is not None
        # 再次调用返回同一实例（懒加载缓存）
        assert runtime.runner() is runner

    def test_memory_isolation(self, tmp_path: Path) -> None:
        """AC-7: 不同项目的 memory 读写各自的 state_dir。"""
        state_a = tmp_path / "proj-a-state"
        state_b = tmp_path / "proj-b-state"
        conn_a = ProjectConnection(id="a", name="A", project_type="local", state_dir=str(state_a))
        conn_b = ProjectConnection(id="b", name="B", project_type="local", state_dir=str(state_b))
        rt_a = ProjectRuntime(conn_a)
        rt_b = ProjectRuntime(conn_b)

        rt_a.memory().remember_fact("k", "from-a")
        rt_b.memory().remember_fact("k", "from-b")

        fact_a = rt_a.memory().get_fact("k")
        fact_b = rt_b.memory().get_fact("k")
        assert fact_a["value"] == "from-a"
        assert fact_b["value"] == "from-b"
        # 验证文件确实落在各自目录
        assert (state_a / "facts.json").exists()
        assert (state_b / "facts.json").exists()

    def test_scheduler(self, tmp_path: Path) -> None:
        # 用空 skills_dir 避免 SkillRunner discover 扫描大量 skill 目录
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        conn = ProjectConnection(
            id="x",
            name="X",
            project_type="local",
            state_dir=str(tmp_path),
            skills_dir=str(skills_dir),
        )
        runtime = ProjectRuntime(conn)
        scheduler = runtime.scheduler()
        assert scheduler is not None
        assert runtime.scheduler() is scheduler


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class TestRouter:
    def test_resolve_default(self, registry: ProjectRegistry) -> None:
        router = Router(registry)
        rt = router.resolve("default")
        assert rt is not None
        assert rt.conn.id == "default"

    def test_resolve_missing_raises(self, registry: ProjectRegistry) -> None:
        from hermes.workbench.errors import NotFoundError

        router = Router(registry)
        with pytest.raises(NotFoundError, match="project not found"):
            router.resolve("nonexistent")

    def test_resolve_caches_runtime(self, registry: ProjectRegistry, tmp_path: Path) -> None:
        registry.add(name="A", project_type="local", state_dir=str(tmp_path), conn_id="a")
        router = Router(registry)
        rt1 = router.resolve("a")
        rt2 = router.resolve("a")
        assert rt1 is rt2  # 同一实例缓存

    def test_try_acquire_within_limit(self, registry: ProjectRegistry) -> None:
        """default max_concurrent=1: first acquire succeeds, second fails until released."""
        router = Router(registry)
        assert router.try_acquire("default") is True
        assert router.try_acquire("default") is False  # 超限
        router.release("default")
        assert router.try_acquire("default") is True  # 释放后可再次获取
        router.release("default")

    def test_try_acquire_exceeds_limit(self, registry: ProjectRegistry, tmp_path: Path) -> None:
        """AC-9: max_concurrent=2, 第三次 acquire 应失败。"""
        registry.add(
            name="limited",
            project_type="local",
            state_dir=str(tmp_path),
            conn_id="limited",
            max_concurrent=2,
        )
        router = Router(registry)
        assert router.try_acquire("limited") is True
        assert router.try_acquire("limited") is True
        assert router.try_acquire("limited") is False  # 超限
        router.release("limited")
        assert router.try_acquire("limited") is True  # 释放后可再次获取

    def test_release_balances(self, registry: ProjectRegistry) -> None:
        router = Router(registry)
        router.try_acquire("default")
        router.release("default")
        # release 后可再次 acquire
        assert router.try_acquire("default") is True
        router.release("default")

    def test_acquire_unknown_project(self, registry: ProjectRegistry) -> None:
        """acquire 未知项目不应崩溃，返回 False。"""
        router = Router(registry)
        assert router.try_acquire("nonexistent") is False

    def test_release_unknown_project_no_crash(self, registry: ProjectRegistry) -> None:
        router = Router(registry)
        router.release("nonexistent")  # 不应抛异常

    def test_concurrent_acquire_thread_safety(self, registry: ProjectRegistry, tmp_path: Path) -> None:
        """多线程并发 acquire/release，任一时刻不超过 max_concurrent=2。"""
        registry.add(
            name="conc",
            project_type="local",
            state_dir=str(tmp_path),
            conn_id="conc",
            max_concurrent=2,
        )
        router = Router(registry)
        peak = {"value": 0}
        current = {"value": 0}
        lock = threading.Lock()
        stop = threading.Event()

        def worker() -> None:
            while not stop.is_set():
                if router.try_acquire("conc"):
                    with lock:
                        current["value"] += 1
                        if current["value"] > peak["value"]:
                            peak["value"] = current["value"]
                    time.sleep(0.02)
                    with lock:
                        current["value"] -= 1
                    router.release("conc")
                else:
                    time.sleep(0.01)

        threads = [threading.Thread(target=worker, name=f"t-{i}") for i in range(8)]
        for t in threads:
            t.start()
        time.sleep(0.5)
        stop.set()
        for t in threads:
            t.join(timeout=2.0)
        # 峰值不超过 max_concurrent
        assert peak["value"] <= 2
        assert peak["value"] >= 1  # 至少有一次成功获取


# ---------------------------------------------------------------------------
# import time for concurrent test
# ---------------------------------------------------------------------------

import time  # noqa: E402
