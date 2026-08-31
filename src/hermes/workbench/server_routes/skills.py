"""Skill routes: list / inspect / sync-run.

从 server.py 拆出的路由域 mixin。
"""
from __future__ import annotations

from hermes.workbench.server_routes.base import RouteBase

from hermes.workbench.errors import NotFoundError


class SkillsRoutes(RouteBase):
    def h_get_skills(self) -> None:
        from hermes.workbench.cli import _make_runner

        specs = _make_runner().discover()
        self._send_json(
            200,
            {
                "skills": [
                    {
                        "name": s.name,
                        "runtime": s.runtime,
                        "description": s.description,
                        "entrypoint": s.entrypoint,
                    }
                    for s in specs
                ]
            },
        )

    def h_get_skill(self, name: str) -> None:
        from hermes.workbench.cli import _make_runner

        spec = _make_runner().get(name)
        if spec is None:
            raise NotFoundError(f"skill not found: {name}")
        self._send_json(
            200,
            {
                "name": spec.name,
                "path": str(spec.path),
                "runtime": spec.runtime,
                "entrypoint": spec.entrypoint,
                "description": spec.description,
                "requires_bins": spec.requires_bins,
            },
        )

    def h_post_skill_run(self, name: str) -> None:
        """Run a skill synchronously.

        Body: {"args": [...], "timeout": N}. Returns the RunResult.
        """
        from hermes.workbench.cli import _make_runner

        body = self._read_json_body()
        runner = _make_runner()
        if runner.get(name) is None:
            raise NotFoundError(f"skill not found: {name}")
        result = runner.run(
            name,
            args=list(body.get("args", []) or []),
            timeout=body.get("timeout"),
        )
        self._send_json(
            200,
            {
                "skill": name,
                "ok": result.ok,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "duration": result.duration,
                "error": result.error,
            },
        )

