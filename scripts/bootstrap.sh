#!/usr/bin/env bash
# bootstrap.sh — 一键内置引导：指定工作空间后运行一次即全量生效。
#
# 解决问题：fresh clone / 环境重置后，Agent 需要手动拼装多个步骤
# （装依赖、修 refspec、分发 skills）才能让 Hermes 能力可用。
# 本脚本把全部依赖收敛为一个幂等入口，重复运行安全且快速
# （依赖 hash 未变时秒级跳过）。
#
# 做五件事：
#   1. 创建/复用 .venv 虚拟环境（自包含，不污染系统 Python）
#   2. 安装依赖 + hermes 本体（hash marker 跳过重复安装）
#   3. 修复 git 远程跟踪（等价 setup-tracking.sh，幂等）
#   4. 启用 opencode 平台目录（仅当用户装有 opencode 时）
#   5. 分发 skills 到本机已安装的各 Agent 平台（skill-sync）
#
# 用法：bash scripts/bootstrap.sh
# 之后：./hermes <command>   或   bash scripts/verify-state.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
MARKER="$VENV/.hermes-deps-hash"

step() { echo "▶ $1"; }

# ── 1. 虚拟环境 ──────────────────────────────────────────────
if [ ! -x "$PY" ]; then
    step "创建虚拟环境 .venv"
    python3 -m venv "$VENV"
fi

# 极少数发行版 venv 不带 pip（缺 ensurepip 包），补一次
if ! "$PY" -m pip --version >/dev/null 2>&1; then
    "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
fi

# ── 2. 依赖安装（hash 未变 + hermes 可导入 → 跳过）──────────
deps_hash() {
    cat "$ROOT/requirements.txt" "$ROOT/requirements-dev.txt" "$ROOT/pyproject.toml" 2>/dev/null \
        | (sha256sum 2>/dev/null || shasum -a 256) | awk '{print $1}'
}
DEPS_HASH="$(deps_hash)"
if [ -n "$DEPS_HASH" ] \
   && [ "$(cat "$MARKER" 2>/dev/null || true)" = "$DEPS_HASH" ] \
   && "$PY" -c "import hermes" >/dev/null 2>&1; then
    step "依赖已是最新（hash 一致，跳过安装）"
else
    step "安装依赖 + hermes（editable，含 dev/content_team extras）"
    # -e ".[dev,content_team]" 是 requirements*.txt 的超集：
    # 核心依赖由 editable 自带，extras 补齐 httpx/fastapi 等测试所需。
    "$PY" -m pip install -q --disable-pip-version-check -e "$ROOT[dev,content_team]"
    [ -n "$DEPS_HASH" ] && echo "$DEPS_HASH" > "$MARKER" || true
fi

# ── 3. git 远程跟踪修复（幂等；非致命——在 main 上工作时只是提示）──
if [ -x "$ROOT/scripts/setup-tracking.sh" ]; then
    step "修复 git 远程跟踪"
    bash "$ROOT/scripts/setup-tracking.sh" || echo "⚠️  tracking 修复未完成（非致命，可稍后重试）" >&2
fi

# ── 4. opencode 平台启用（装有 opencode 才创建，不装不碰）────
if [ -d "$HOME/.opencode" ] && [ ! -d "$HOME/.opencode/skill" ]; then
    step "检测到 opencode，创建技能目录 ~/.opencode/skill"
    mkdir -p "$HOME/.opencode/skill"
fi

# ── 5. skills 分发（非致命：没有已装平台时仅提示）────────────
step "分发 skills 到本机各 Agent 平台"
if ! "$VENV/bin/hermes" skill-sync add --all >/dev/null 2>&1; then
    echo "⚠️  skill-sync add 未完成（可稍后重试）" >&2
fi
if ! "$VENV/bin/hermes" skill-sync sync; then
    echo "⚠️  skill-sync sync 未完成（不影响核心能力，可稍后重试）" >&2
fi

echo ""
echo "✅ 引导完成。"
echo "   CLI 入口:   $ROOT/hermes <command>"
echo "   状态验证:   bash scripts/verify-state.sh"
