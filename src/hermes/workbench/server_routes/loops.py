"""Loop routes: loop list / dispatch trajectory / offline verify.

从 server.py 拆出的路由域 mixin（ADR-0017 / ADR-0020）。
"""
from __future__ import annotations

from hermes.workbench.server_routes.base import RouteBase

from hermes.workbench.errors import NotFoundError


class LoopRoutes(RouteBase):
    def h_get_loops(self) -> None:
        """GET /loops — list loops that have a trajectory.jsonl (ADR-0020)."""
        from hermes.loop import loops_dir

        root = loops_dir()
        loops: list[str] = []
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "trajectory.jsonl").exists():
                    loops.append(child.name)
        self._send_json(200, {"loops": loops})

    def h_get_loop_trajectory(self, name: str) -> None:
        """GET /loops/<name>/trajectory — return dispatch trajectory events."""
        from hermes.loop import loops_dir
        from hermes.trajectory import TrajectoryLogger

        self._validate_loop_name(name)
        path = loops_dir() / name / "trajectory.jsonl"
        if not path.exists():
            raise NotFoundError(f"loop not found: {name}")
        events = TrajectoryLogger(path).events()
        self._send_json(200, {"events": [e.to_dict() for e in events]})

    def h_get_loop_trajectory_verify(self, name: str) -> None:
        """GET /loops/<name>/trajectory/verify — offline audit result."""
        from hermes.loop import loops_dir
        from hermes.trajectory import verify_trajectory

        self._validate_loop_name(name)
        path = loops_dir() / name / "trajectory.jsonl"
        if not path.exists():
            raise NotFoundError(f"loop not found: {name}")
        result = verify_trajectory(path)
        self._send_json(200, result)

