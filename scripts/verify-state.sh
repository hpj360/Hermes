#!/usr/bin/env bash
# verify-state.sh — 一键状态验证脚本
#
# 解决问题：Fresh clone 后 git refspec 可能只跟踪 main，
# 导致 `git status` 无法显示 trae/agent-glOxQF 的同步状态，
# Agent 误判"工作未完成/丢失"而重复执行已完成的工作。
#
# 本脚本不依赖 refspec，直接用 `git ls-remote` 比较本地与远程 SHA，
# 并运行 pytest + ruff + 关键文件检查，输出明确的状态判定。
#
# 用法：bash scripts/verify-state.sh
# 退出码：0 = 全部通过且已同步；1 = 有问题需要处理

set -euo pipefail

BRANCH="trae/agent-glOxQF"
PASS=0
FAIL=0
WARN=0

ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
warn() { echo "  ⚠️  $1"; WARN=$((WARN+1)); }

echo "═══════════════════════════════════════════════════════════════"
echo "  Hermes 状态验证  (branch: $BRANCH)"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. Git 同步状态（不依赖 refspec）──────────────────────────
echo ""
echo "── 1. Git 同步状态 ──"

LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "NONE")
REMOTE_SHA=$(git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}')

if [ -z "$REMOTE_SHA" ]; then
    fail "远程分支 $BRANCH 不存在（工作未推送）"
elif [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
    ok "本地与远程同步 (SHA: ${LOCAL_SHA:0:12})"
else
    fail "本地 ($LOCAL_SHA) 与远程 ($REMOTE_SHA) 不同步"
    echo "       本地领先: $(git log --oneline "$REMOTE_SHA"..HEAD 2>/dev/null | wc -l) 个提交未推送"
    echo "       远程领先: $(git log --oneline HEAD.."$REMOTE_SHA" 2>/dev/null | wc -l) 个提交未拉取"
fi

# 工作树是否干净
if [ -z "$(git status --porcelain)" ]; then
    ok "工作树干净（无未提交修改）"
else
    warn "工作树有未提交修改："
    git status --short | head -10 | sed 's/^/       /'
fi

# ── 2. 测试套件 ──────────────────────────────────────────────
echo ""
echo "── 2. 测试套件 ──"

if python -m pytest tests/ -q 2>&1 | tail -1 | grep -q "passed"; then
    RESULT=$(python -m pytest tests/ -q 2>&1 | tail -1)
    ok "pytest: $RESULT"
else
    fail "pytest 运行失败（运行 `pytest tests/ -v` 查看详情）"
fi

# ── 3. 代码质量 ──────────────────────────────────────────────
echo ""
echo "── 3. 代码质量 ──"

if ruff check src/ tests/ 2>&1 | grep -q "All checks passed"; then
    ok "ruff: All checks passed"
else
    fail "ruff 有错误（运行 `ruff check src/ tests/` 查看）"
fi

# ── 4. 关键文件存在性 ────────────────────────────────────────
echo ""
echo "── 4. 关键文件 ──"

for f in \
    "src/hermes/runner.py" \
    "src/hermes/loop.py" \
    "src/hermes/profile.py" \
    "tests/conftest.py" \
    "tests/test_loop.py" \
    "knowledge/working-principles.md" \
    "knowledge/architecture.md" \
    "knowledge/builder-checker-loop.md" \
    "manifest.json" \
    "AGENTS.md" \
    "scripts/verify-state.sh" \
    "scripts/setup-tracking.sh"; do
    if [ -f "$f" ]; then
        ok "$f 存在"
    else
        fail "$f 缺失"
    fi
done

# ── 5. 关键代码模式检查 ──────────────────────────────────────
echo ""
echo "── 5. 关键代码模式 ──"

if grep -q "_terminal_status_to_stop" src/hermes/runner.py 2>/dev/null; then
    ok "runner.py: _terminal_status_to_stop helper 已定义"
else
    fail "runner.py: _terminal_status_to_stop helper 缺失"
fi

if grep -q "_RULE_HEADING_RE" src/hermes/profile.py 2>/dev/null; then
    ok "profile.py: 重写的解析器已落地"
else
    fail "profile.py: 解析器重写未落地"
fi

if grep -q "_isolated_loops_dir" tests/conftest.py 2>/dev/null; then
    ok "conftest.py: 测试隔离 fixture 已配置"
else
    fail "conftest.py: 测试隔离 fixture 缺失"
fi

# ── 6. 措辞一致性 ────────────────────────────────────────────
echo ""
echo "── 6. 措辞一致性 ──"

STALE=$(grep -rn -E "(六条|6 条|6条|six stop|6 stop)" src/ tests/ knowledge/ manifest.json 2>/dev/null | grep -v __pycache__ | wc -l)
if [ "$STALE" = "0" ]; then
    ok "无残留 '六条/6 stop' 措辞"
else
    fail "发现 $STALE 处残留 '六条/6 stop' 措辞"
fi

# ── 7. 工作规则持久化 ────────────────────────────────────────
echo ""
echo "── 7. 工作规则 ──"

if grep -q "第一性原理" knowledge/working-principles.md 2>/dev/null && \
   grep -q "对抗性审查" knowledge/working-principles.md 2>/dev/null; then
    ok "两条工作规则已持久化到 working-principles.md"
else
    fail "工作规则未完整持久化"
fi

# ── 汇总 ─────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  汇总: ✅ $PASS 通过  |  ❌ $FAIL 失败  |  ⚠️  $WARN 警告"
echo "═══════════════════════════════════════════════════════════════"

if [ "$FAIL" = "0" ]; then
    echo ""
    echo "  🎯 判定: 全部通过，工作已完成并同步。无需重复执行。"
    echo "  下一步: 如需继续新任务，请遵循 AGENTS.md 中的工作约定。"
    exit 0
else
    echo ""
    echo "  🚨 判定: 有 $FAIL 项失败，需要处理。"
    echo "  下一步: 根据上述 ❌ 项修复问题，修复后重新运行本脚本验证。"
    exit 1
fi
