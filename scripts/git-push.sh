#!/usr/bin/env bash
# Hermes Git Push Guard
#
# 根治"push 幻觉"：模型 git push 后脑补成功 hash，实际远端没收到。
# 做法：把 push + ls-remote 校验绑成原子操作，SHA 不一致就非零退出。
#
# 用法:
#   bash scripts/git-push.sh                # push 当前分支并校验
#   bash scripts/git-push.sh --branch xxx   # 指定分支（默认 trae/agent-glOxQF）
#
# 退出码:
#   0 = 推送成功且本地与远端 SHA 一致
#   1 = push 失败 或 SHA 不一致（幻觉/网络波动/权限问题）

set -uo pipefail

BRANCH="trae/agent-glOxQF"
REMOTE="origin"

# 解析参数
while [ $# -gt 0 ]; do
    case "$1" in
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --remote)
            REMOTE="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1" >&2
            exit 1
            ;;
    esac
done

# ── 1. 推送 ──────────────────────────────────────────────────
echo "→ Pushing to $REMOTE/$BRANCH..."
if ! git push "$REMOTE" "$BRANCH"; then
    echo ""
    echo "✗ git push 失败（退出码非零）" >&2
    echo "  可能原因: 权限阻断 / 网络波动 / 非快进 / refspec 错误" >&2
    exit 1
fi

# ── 2. 校验远端实际状态（不依赖 refspec）──────────────────────
# push 的 stdout 会显示 hash，但那不可信——模型可能没读到 stderr，
# 或 push 实际写了别的 ref。唯一可信源是 ls-remote 返回的远端 SHA。
LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "NONE")
REMOTE_SHA=$(git ls-remote "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}')

echo ""
echo "→ 校验推送结果："
echo "  本地 SHA: $LOCAL_SHA"
echo "  远端 SHA: ${REMOTE_SHA:-（远端无此分支）}"

if [ -z "$REMOTE_SHA" ]; then
    echo ""
    echo "✗ 校验失败：远端分支 $BRANCH 不存在" >&2
    echo "  push 命令退出码为 0，但远端没有该分支——疑似 push 幻觉" >&2
    exit 1
fi

if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo ""
    echo "✗ 校验失败：本地与远端 SHA 不一致" >&2
    echo "  本地领先: $(git log --oneline "$REMOTE_SHA"..HEAD 2>/dev/null | wc -l) 个提交未推送" >&2
    echo "  远端领先: $(git log --oneline HEAD.."$REMOTE_SHA" 2>/dev/null | wc -l) 个提交未拉取" >&2
    echo "  可能原因: push 部分失败 / 网络波动 / 并发推送覆盖" >&2
    exit 1
fi

echo ""
echo "✓ 推送成功，本地与远端 SHA 一致"
