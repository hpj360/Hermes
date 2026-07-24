#!/usr/bin/env bash
# setup-tracking.sh — 修复 fresh clone 后的 git refspec 盲点
#
# 问题：Fresh clone 后 remote.origin.fetch refspec 可能只跟踪 main，
# 导致 origin/trae/agent-glOxQF 远程跟踪引用不存在，
# `git status` 无法显示 trae/agent-glOxQF 的同步状态。
#
# 本脚本为 trae/agent-glOxQF 分支添加专用的 fetch refspec 并设置 upstream。
# Fresh clone 后运行一次即可。
#
# 用法：bash scripts/setup-tracking.sh
# 幂等：可重复运行，不会产生副作用

set -euo pipefail

BRANCH="trae/agent-glOxQF"
REFSPEC="+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"

echo "── 配置 git 远程跟踪 ──"

# 1. 检查 refspec 是否已存在（避免重复添加）
EXISTING=$(git config --get-all remote.origin.fetch 2>/dev/null || echo "")
if echo "$EXISTING" | grep -qF "$BRANCH"; then
    echo "  ✅ refspec 已配置（跳过）"
else
    git config --add remote.origin.fetch "$REFSPEC"
    echo "  ✅ 已添加 refspec: $REFSPEC"
fi

# 2. 拉取远程引用
git fetch origin "$BRANCH" 2>&1 | grep -v "remote: Enumerating" | sed 's/^/  /' || true
echo "  ✅ 已 fetch 远程分支"

# 3. 设置 upstream 跟踪关系（如果当前在该分支上）
CURRENT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ "$CURRENT" = "$BRANCH" ]; then
    if git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
        git branch --set-upstream-to="origin/$BRANCH" "$BRANCH" 2>/dev/null || true
        echo "  ✅ 已设置 upstream: $BRANCH → origin/$BRANCH"
    else
        echo "  ⚠️  origin/$BRANCH 引用不存在，可能远程分支尚未创建"
    fi
else
    echo "  ℹ️  当前不在 $BRANCH 分支上（当前: $CURRENT），跳过 upstream 设置"
fi

echo ""
echo "── 验证 ──"
git branch -vv | grep "$BRANCH" | sed 's/^/  /'
echo ""
echo "  ✅ 完成。现在 \`git status\` 会正确显示同步状态。"
