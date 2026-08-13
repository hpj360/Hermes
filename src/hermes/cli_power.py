"""Power CLI subcommands: sh / diff / context / init.

借鉴 Hermes Agent v0.20.0 的 CLI 交互能力，适配为控制平面层的实用命令。
这些命令直接执行，不消耗 model turn——适合在 hermes CLI 上下文中快速执行
shell 操作、查看 diff、查看 loop 上下文、初始化项目骨架。

设计（与 cli_loop.py 风格一致）：
- 薄 handler：每个 cmd_* 函数只做一件事，返回退出码。
- 退出码：0=success，1=soft fail（命令返回非零、loop 不存在），
  2=hard error（缺参数、subprocess 崩溃等）。
- graceful degradation：失败被捕获并报告，绝不崩溃 CLI（main 已有兜底）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from hermes.config import get_settings
from hermes.loop import get_loop, get_loop_history, list_loops, loop_metrics


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ── Command handlers ────────────────────────────────────────────────


def cmd_sh(args: argparse.Namespace) -> int:
    """执行 shell 命令，不消耗 model turn。

    对应 v0.20.0 的 `!` 命令。用 subprocess 执行命令并回显结果。
    `--json` 时输出结构化 JSON（含 exit_code/stdout/stderr）。
    命令本身返回非零退出码时，本命令返回 1（soft fail）。
    缺少 command 参数时返回 2（hard error）。
    """
    command: str | None = getattr(args, "shell_command", None)
    if not command:
        print("Error: `hermes sh` requires a command. Usage: hermes sh '<command>'")
        return 2

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        print(f"Error: failed to execute command: {exc}")
        return 2

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    exit_code = result.returncode

    if args.json:
        _print_json({
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        })
    else:
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)

    return 0 if exit_code == 0 else 1


def cmd_diff(args: argparse.Namespace) -> int:
    """显示 git diff。

    对应 v0.20.0 的 `/diff`。在项目根目录执行 `git diff`，可选 --staged /
    --stat。直接回显 git diff 的原始输出。git 非零退出（如非 git 仓库）视为
    soft fail。
    """
    settings = get_settings()
    root = settings.hermes_project_root

    cmd: list[str] = ["git", "diff"]
    if args.staged:
        cmd.append("--staged")
    if args.stat:
        cmd.append("--stat")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        print(f"Error: failed to run git: {exc}")
        return 2

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return 0 if result.returncode == 0 else 1


def cmd_context(args: argparse.Namespace) -> int:
    """显示 loop 上下文摘要。

    对应 v0.20.0 的 `/context`。无参数时列出所有 loop 的概览；
    指定 loop-name 时显示该 loop 的详细状态（轮次/预算/状态/最近失败项/
    协作指标）。复用 loop.py 的 get_loop/list_loops/loop_metrics/
    get_loop_history。loop 不存在返回 1。
    """
    loop_name: str | None = getattr(args, "loop_name", None)

    if not loop_name:
        # 概览：列出所有 loop
        loops = list_loops()
        if not loops:
            print("No loops found. Run `hermes loop init <name>` to create one.")
            return 0
        print(f"Active loops ({len(loops)}):")
        for lp in loops:
            print(
                f"  {lp.name:<24} pattern={lp.pattern:<18} "
                f"stage={lp.stage.value:<10} status={lp.status.value:<14} "
                f"round={lp.current_round}/{lp.max_rounds}"
            )
        return 0

    # 详细状态
    loop = get_loop(loop_name)
    if loop is None:
        print(f"Loop '{loop_name}' not found.")
        return 1

    metrics = loop_metrics(loop_name)
    history = get_loop_history(loop_name)

    print(f"Loop: {loop.name}")
    print(f"  Pattern: {loop.pattern}")
    print(f"  Stage:   {loop.stage.value}")
    print(f"  Status:  {loop.status.value}")
    print(f"  Round:   {loop.current_round}/{loop.max_rounds}")
    print(f"  Budget:  {loop.budget_used_tokens}/{loop.budget_limit_tokens} tokens")

    if metrics.get("success"):
        print(f"  Pass rate:    {metrics.get('pass_rate', 0)}%")
        print(f"  Total tokens: {metrics.get('total_tokens', 0)}")

    # 最近失败项（最多展示 3 条）
    rounds: list[dict[str, Any]] = []
    if history.get("success"):
        raw_rounds = history.get("rounds", [])
        if isinstance(raw_rounds, list):
            rounds = [r for r in raw_rounds if isinstance(r, dict)]
    failed_rounds = [r for r in rounds if not r.get("passed")]
    if failed_rounds:
        print(f"  Recent failures ({len(failed_rounds)}):")
        for r in failed_rounds[-3:]:
            summary = str(r.get("result_summary") or "")[:80]
            print(f"    Round {r.get('round_num', '?')}: {summary}")

    # 协作指标（multi-agent 跨轮次聚合）
    if loop.total_role_violations:
        print(f"  Role violations: {loop.total_role_violations}")
    if loop.failure_attribution_counts:
        print("  Failure attribution:")
        for attr, count in loop.failure_attribution_counts.items():
            print(f"    {attr}: {count}")
    return 0


def _generate_agents_skeleton(root: Path) -> str:
    """根据项目结构生成 AGENTS.md 骨架内容。"""
    # 扫描关键目录是否存在
    dirs: list[str] = []
    for name in ("src/hermes", "tests", "skills", "knowledge", "scripts"):
        if (root / name).exists():
            dirs.append(name)

    dir_lines = "\n".join(f"- `{d}/`" for d in dirs) if dirs else "- (none detected)"

    return f"""# AGENTS.md — {root.name} 工作约定

> **任何 Agent 在新会话开始时必须先阅读本文件。**

---

## 项目概述

{root.name} 项目。本文件由 `hermes init` 自动生成骨架，可按需补充。

## 目录结构

{dir_lines}

## 开发命令

```bash
# 安装依赖
pip install -q -r requirements.txt -r requirements-dev.txt && pip install -e -q .

# 测试
python -m pytest

# 静态检查
ruff check src/hermes tests
mypy src/hermes
```

## 工作约定

- 修改前先阅读现有代码，遵循既有风格与模式。
- 提交前运行测试与静态检查。
- 复杂任务后进行多 Agent 对抗性审查。
"""


def cmd_init(args: argparse.Namespace) -> int:
    """扫描项目结构，生成或更新 AGENTS.md。

    对应 v0.20.0 的 `/init`。如果 AGENTS.md 已存在，提示用户手动确认更新，
    不覆盖用户自定义内容；否则生成骨架文件。
    """
    settings = get_settings()
    root = settings.hermes_project_root
    agents_path = root / "AGENTS.md"

    if agents_path.exists():
        print(f"AGENTS.md already exists at {agents_path}")
        print("Not overwriting — to update, manually merge the skeleton below:")
        print()
        print(_generate_agents_skeleton(root), end="")
        return 0

    skeleton = _generate_agents_skeleton(root)
    try:
        agents_path.write_text(skeleton, encoding="utf-8")
    except OSError as exc:
        print(f"Error: failed to write AGENTS.md: {exc}")
        return 2
    print(f"Generated {agents_path}")
    return 0


# ── Subparser registration ──────────────────────────────────────────


_DOCKERFILE_TEMPLATE = """# Hermes 运行时镜像（由 `hermes deploy` 生成）
FROM python:3.12-slim

WORKDIR /app

# 先拷贝依赖清单以利用 Docker 层缓存
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 安装 hermes 包（editable 或 sdist 均可，这里用 sdist 保持镜像自包含）
COPY . .
RUN pip install --no-cache-dir .

# 状态目录（持久化卷挂载点）
ENV HERMES_STATE_DIR=/app/.state \\
    HERMES_CACHE_DIR=/app/.cache

EXPOSE 8000

CMD ["hermes", "workbench", "serve", "--host", "0.0.0.0", "--port", "8000"]
"""

_COMPOSE_TEMPLATE = """# Hermes 工作台编排（由 `hermes deploy` 生成）
services:
  hermes:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - hermes-state:/app/.state
      - hermes-cache:/app/.cache
    env_file:
      - .env
    restart: unless-stopped

volumes:
  hermes-state:
  hermes-cache:
"""

_DEPLOY_README_TEMPLATE = """# Hermes 部署指南（由 `hermes deploy` 生成）

## Docker 本地运行

```bash
docker compose up --build
```

## Render

1. 创建 Web Service，连接本仓库。
2. Build Command: `pip install -r requirements.txt && pip install .`
3. Start Command: `hermes workbench serve --host 0.0.0.0 --port $PORT`
4. 在 Environment 中配置 `.env` 里的密钥变量。

## Fly.io

```bash
fly launch --no-deploy
fly deploy
```

## Railway

1. New Project → Deploy from GitHub。
2. 启动命令设为 `hermes workbench serve --host 0.0.0.0 --port $PORT`。
3. 在 Variables 中配置密钥。
"""


def cmd_deploy(args: argparse.Namespace) -> int:
    """生成部署资产（Dockerfile / docker-compose.yml / deploy 说明）。

    Output directory defaults to ``deploy/`` under the project root. Generated
    files are plain text; re-running overwrites them (they are templates).
    """
    settings = get_settings()
    out_dir = Path(args.output) if args.output else settings.hermes_project_root / "deploy"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Error: failed to create {out_dir}: {exc}")
        return 2

    files = {
        "Dockerfile": _DOCKERFILE_TEMPLATE,
        "docker-compose.yml": _COMPOSE_TEMPLATE,
        "README.md": _DEPLOY_README_TEMPLATE,
    }
    for name, content in files.items():
        try:
            (out_dir / name).write_text(content, encoding="utf-8")
            print(f"  wrote {out_dir / name}")
        except OSError as exc:
            print(f"Error: failed to write {name}: {exc}")
            return 2
    print(f"Deploy assets generated in {out_dir}")
    return 0


def add_power_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """注册 power 子命令：sh / diff / context / init（均为顶层子命令）。"""
    # sh —— 执行 shell 命令
    p_sh = sub.add_parser("sh", help="Execute a shell command (no model turn)")
    p_sh.add_argument(
        "shell_command", nargs="?", default=None, help="Shell command to execute"
    )
    p_sh.add_argument(
        "--json", action="store_true",
        help="Output JSON with exit_code/stdout/stderr",
    )
    p_sh.set_defaults(func=cmd_sh)

    # diff —— 查看 git diff
    p_diff = sub.add_parser("diff", help="Show git diff")
    p_diff.add_argument("--staged", action="store_true", help="Only show staged changes")
    p_diff.add_argument("--stat", action="store_true", help="Show diffstat only")
    p_diff.set_defaults(func=cmd_diff)

    # context —— 查看 loop 上下文
    p_ctx = sub.add_parser("context", help="Show loop context summary")
    p_ctx.add_argument(
        "loop_name", nargs="?", default=None,
        help="Loop name (omit to list all loops)",
    )
    p_ctx.set_defaults(func=cmd_context)

    # init —— 生成/更新 AGENTS.md
    p_init = sub.add_parser("init", help="Generate or update AGENTS.md")
    p_init.set_defaults(func=cmd_init)

    # deploy —— 生成部署资产（Dockerfile / docker-compose / 说明）
    p_deploy = sub.add_parser("deploy", help="Generate deploy assets (Dockerfile, compose)")
    p_deploy.add_argument(
        "--output", default=None, help="Output directory (default: <project>/deploy)"
    )
    p_deploy.set_defaults(func=cmd_deploy)
