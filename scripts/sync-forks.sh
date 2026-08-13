#!/usr/bin/env bash
# Hermes 多仓同步脚本
#
# 把主仓 (hermes) 的沉淀资产同步到各 fork 仓，保持单一信源。
# 默认 dry-run：只打印将要执行的操作，不修改任何文件。
# 必须显式传 --apply 才真正执行。
#
# 同步范围（仅资产层，不动各 fork 的业务代码）：
#   skills/    —— 全部 skill 目录
#   knowledge/ —— 全部知识文档
#   manifest.json —— skill/knowledge 清单
#
# 用法:
#   bash scripts/sync-forks.sh                  # dry-run，打印 diff
#   bash scripts/sync-forks.sh --apply          # 真正执行同步
#   bash scripts/sync-forks.sh --targets content-team hermes-workbench  # 指定目标
#
# 退出码:
#   0 = 成功（dry-run 或 apply 均成功）
#   1 = 参数错误 / 目标仓不存在 / 同步失败

set -uo pipefail

# ── 目标仓配置：名称 → 相对主仓的路径 ─────────────────────────────
# 采用相对路径（相对脚本所在主仓的上一级目录），适配多机布局。
declare -A TARGET_PATHS=(
    ["content-team"]="../content-team"
    ["hermes-workbench"]="../Hermes-workbench/hermes-workbench-"
    ["hermes-kb"]="../hermes-kb/hermes-knowledge-base"
)

APPLY=0
TARGETS=()
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 解析参数 ────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --apply)
            APPLY=1
            shift
            ;;
        --targets)
            shift
            while [ $# -gt 0 ] && [[ "$1" != --* ]]; do
                TARGETS+=("$1")
                shift
            done
            ;;
        --help|-h)
            echo "用法: bash scripts/sync-forks.sh [--apply] [--targets NAME...]"
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

# 未指定 --targets 时同步全部
if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=("${!TARGET_PATHS[@]}")
fi

MODE="dry-run"
if [ "$APPLY" -eq 1 ]; then
    MODE="apply"
fi
echo "== Hermes 多仓同步（$MODE）=="
echo "主仓: $MAIN_REPO"
echo "目标: ${TARGETS[*]}"
echo ""

# ── 校验主仓资产存在 ────────────────────────────────────────────
for asset in "skills" "knowledge" "manifest.json"; do
    if [ ! -e "$MAIN_REPO/$asset" ]; then
        echo "✗ 主仓缺少资产: $asset" >&2
        exit 1
    fi
done

# ── 对每个目标仓执行同步 ────────────────────────────────────────
FAILED=0
for name in "${TARGETS[@]}"; do
    path="${TARGET_PATHS[$name]:-}"
    if [ -z "$path" ]; then
        echo "✗ 未知目标仓: $name" >&2
        FAILED=1
        continue
    fi
    target="$MAIN_REPO/$path"
    # 规范化路径（解析 .. 符号链接），失败则跳过
    if [ ! -d "$target" ]; then
        echo "✗ 目标仓不存在: $name ($path)" >&2
        FAILED=1
        continue
    fi
    target="$(cd "$target" && pwd)"

    echo "→ [$name] $target"

    for asset in "skills" "knowledge"; do
        src="$MAIN_REPO/$asset"
        dst="$target/$asset"
        if [ ! -d "$dst" ]; then
            echo "    (跳过 $asset: 目标无此目录)"
            continue
        fi
        if [ "$APPLY" -eq 1 ]; then
            # rsync 若可用则用 rsync，否则用 cp -r 兜底
            if command -v rsync >/dev/null 2>&1; then
                rsync -a --delete "$src/" "$dst/" && echo "    ✓ 已同步 $asset"
            else
                rm -rf "$dst" && cp -r "$src" "$dst" && echo "    ✓ 已同步 $asset (cp 兜底)"
            fi
        else
            echo "    [dry-run] 将同步 $asset → $dst"
        fi
    done

    # manifest.json
    if [ "$APPLY" -eq 1 ]; then
        cp "$MAIN_REPO/manifest.json" "$target/manifest.json" && echo "    ✓ 已同步 manifest.json"
    else
        echo "    [dry-run] 将同步 manifest.json → $target/manifest.json"
    fi
    echo ""
done

if [ "$FAILED" -ne 0 ]; then
    echo "✗ 同步过程中有失败项" >&2
    exit 1
fi

echo "✓ 完成（$MODE）"
