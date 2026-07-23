"""Hermes Workbench 客户端 SDK（零依赖 urllib）。

供其他仓库调用 Workbench HTTP API，实现跨仓库统一调度。

用法:
    from workbench_client import WorkbenchClient

    client = WorkbenchClient("http://127.0.0.1:8080")

    # 跨源查询
    skills = client.list_skills()
    agents = client.list_agents(source="pm-team")

    # 创建并运行任务
    result = client.create_task(plan=[{"skill": "weather", "args": ["Beijing"]}], run=True)

    # GitHub 同步
    sync_result = client.github_sync(repo="hpj360/Hermes", label="workbench")

也可作为 CLI 使用:
    python -m workbench_client --base-url http://127.0.0.1:8080 skills
    python -m workbench_client --base-url http://127.0.0.1:8080 summary
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__all__ = ["WorkbenchClient", "WorkbenchClientError"]
__version__ = "0.1.0"


class WorkbenchClientError(Exception):
    """Workbench 客户端错误，包含 HTTP 状态码与响应体。"""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class WorkbenchClient:
    """Hermes Workbench HTTP API 的轻量客户端（零依赖）。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None, params: dict[str, str] | None = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            from urllib.parse import urlencode

            url += f"?{urlencode(params)}"

        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw)
        except HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise WorkbenchClientError(
                f"HTTP {e.code} {e.reason}: {error_body}", status_code=e.code, body=error_body
            ) from e
        except URLError as e:
            raise WorkbenchClientError(f"connection error: {e.reason}") from e

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """健康检查。"""
        return self._request("GET", "/health")

    # ------------------------------------------------------------------
    # Registry (统一注册中心)
    # ------------------------------------------------------------------

    def list_sources(self) -> dict[str, Any]:
        """列出所有注册源（本地 + GitHub 仓库）。"""
        return self._request("GET", "/registry/sources")

    def list_skills(self, source: str | None = None) -> dict[str, Any]:
        """跨源列出所有 skills。"""
        params = {"source": source} if source else None
        return self._request("GET", "/registry/skills", params=params)

    def list_agents(self, source: str | None = None) -> dict[str, Any]:
        """跨源列出所有 agents。"""
        params = {"source": source} if source else None
        return self._request("GET", "/registry/agents", params=params)

    def list_knowledge(self, source: str | None = None) -> dict[str, Any]:
        """跨源列出所有知识文档。"""
        params = {"source": source} if source else None
        return self._request("GET", "/registry/knowledge", params=params)

    def get_user_profile(self) -> dict[str, Any]:
        """获取合并后的用户画像。"""
        return self._request("GET", "/registry/user")

    def registry_summary(self) -> dict[str, Any]:
        """注册中心摘要统计。"""
        return self._request("GET", "/registry/summary")

    # ------------------------------------------------------------------
    # Skills (本地)
    # ------------------------------------------------------------------

    def list_local_skills(self) -> dict[str, Any]:
        """列出本地 skills。"""
        return self._request("GET", "/skills")

    def get_skill(self, name: str) -> dict[str, Any]:
        """获取单个 skill 详情。"""
        return self._request("GET", f"/skills/{name}")

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def list_facts(self) -> dict[str, Any]:
        """列出所有 facts。"""
        return self._request("GET", "/memory/facts")

    def set_fact(self, key: str, value: Any) -> dict[str, Any]:
        """创建/更新 fact。"""
        return self._request("POST", "/memory/facts", body={"key": key, "value": value})

    def get_fact(self, key: str) -> dict[str, Any]:
        """获取单个 fact。"""
        return self._request("GET", f"/memory/facts/{key}")

    def delete_fact(self, key: str) -> None:
        """删除 fact。"""
        self._request("DELETE", f"/memory/facts/{key}")

    def list_episodes(self, kind: str | None = None) -> dict[str, Any]:
        """列出 episodes。"""
        params = {"kind": kind} if kind else None
        return self._request("GET", "/memory/episodes", params=params)

    def get_profile(self) -> dict[str, Any]:
        """获取用户画像（L3 memory）。"""
        return self._request("GET", "/memory/profile")

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def list_tasks(self) -> dict[str, Any]:
        """列出所有任务。"""
        return self._request("GET", "/tasks")

    def get_task(self, task_id: str) -> dict[str, Any]:
        """获取任务详情。"""
        return self._request("GET", f"/tasks/{task_id}")

    def create_task(
        self,
        plan: list[dict[str, Any]],
        run: bool = False,
        task_id: str | None = None,
        mode: str = "oneshot",
        max_rounds: int = 1,
    ) -> dict[str, Any]:
        """创建任务，可选立即运行。"""
        body: dict[str, Any] = {"plan": plan, "mode": mode, "max_rounds": max_rounds}
        if task_id:
            body["task_id"] = task_id
        if run:
            body["run"] = True
        return self._request("POST", "/tasks", body=body)

    def run_task(self, task_id: str) -> dict[str, Any]:
        """运行已有任务。"""
        return self._request("POST", f"/tasks/{task_id}/run")

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        """取消任务。"""
        return self._request("POST", f"/tasks/{task_id}/cancel")

    # ------------------------------------------------------------------
    # GitHub Sync
    # ------------------------------------------------------------------

    def github_sync(self, repo: str, label: str = "workbench") -> dict[str, Any]:
        """触发 GitHub Issues → Workbench 任务同步。"""
        return self._request("GET", "/github/sync", params={"repo": repo, "label": label})


# ---------------------------------------------------------------------------
# CLI 入口（python -m workbench_client）
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="workbench-client",
        description="Hermes Workbench 客户端 — 跨仓库调用工具",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="Workbench API 地址")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health", help="健康检查")
    sub.add_parser("summary", help="注册中心摘要")
    sub.add_parser("sources", help="列出注册源")
    p_skills = sub.add_parser("skills", help="跨源列出 skills")
    p_skills.add_argument("--source", default=None)
    p_agents = sub.add_parser("agents", help="跨源列出 agents")
    p_agents.add_argument("--source", default=None)
    p_know = sub.add_parser("knowledge", help="跨源列出知识文档")
    p_know.add_argument("--source", default=None)
    sub.add_parser("user", help="用户画像")
    sub.add_parser("tasks", help="列出任务")
    p_sync = sub.add_parser("sync", help="GitHub 同步")
    p_sync.add_argument("--repo", required=True)
    p_sync.add_argument("--label", default="workbench")
    p_run = sub.add_parser("run", help="运行 skill plan")
    p_run.add_argument("--plan", required=True, help="JSON plan, e.g. [{\"skill\":\"weather\"}]")

    args = parser.parse_args(argv)
    client = WorkbenchClient(args.base_url)

    try:
        if args.cmd == "health":
            result = client.health()
        elif args.cmd == "summary":
            result = client.registry_summary()
        elif args.cmd == "sources":
            result = client.list_sources()
        elif args.cmd == "skills":
            result = client.list_skills(source=args.source)
        elif args.cmd == "agents":
            result = client.list_agents(source=args.source)
        elif args.cmd == "knowledge":
            result = client.list_knowledge(source=args.source)
        elif args.cmd == "user":
            result = client.get_user_profile()
        elif args.cmd == "tasks":
            result = client.list_tasks()
        elif args.cmd == "sync":
            result = client.github_sync(repo=args.repo, label=args.label)
        elif args.cmd == "run":
            plan = json.loads(args.plan)
            result = client.create_task(plan=plan, run=True)
        else:
            parser.print_help()
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except WorkbenchClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
