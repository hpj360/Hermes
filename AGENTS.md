# AGENTS.md — Hermes Agent 工作约定

> **任何 Agent 在新会话开始时必须先阅读本文件。**
> 本文件持久化到仓库，fresh clone 后自动继承，确保跨会话/跨环境的一致性。

---

## 会话开始检查清单（必做，3 步）

### 第 1 步：安装依赖（如未安装）

```bash
pip install -q -r requirements.txt -r requirements-dev.txt && pip install -e -q .
```

### 第 2 步：修复 git 远程跟踪 + 验证状态

```bash
bash scripts/setup-tracking.sh   # 修复 refspec 盲点（幂等，可重复运行）
bash scripts/verify-state.sh     # 一键状态验证
```

### 第 3 步：根据 `verify-state.sh` 输出决定下一步

| `verify-state.sh` 退出码 | 含义 | 下一步 |
|--------------------------|------|--------|
| 0（全部 ✅） | 工作已完成并同步 | **不要重复执行已完成的工作。** 询问用户新任务 |
| 1（有 ❌） | 有问题需要处理 | 根据 ❌ 项修复，修复后重新运行脚本验证 |

**关键**：`verify-state.sh` 直接用 `git ls-remote` 比较本地与远程 SHA，**不依赖 git refspec**。即使 fresh clone 后 refspec 盲点存在，它也能正确判断工作是否已推送。不要用 `git status` 作为"工作是否完成"的唯一依据——它可能因 refspec 缺失而显示异常。

---

## 半自动原则（Gated Mode）

> 来源：文章《从Vibe Coding到Harness》第五章"半自动模式才是当前的最优解"

**核心原则**：AI 对自己生成的东西天然无"否决欲望"——这是模型级偏置，不是 prompt 层面能控制的。关键节点必须有人。

### 使用方式

```bash
# 每轮结束后暂停，等待人工确认后才继续下一轮
hermes loop continuous my-task --gated
```

### 设计约束

1. **Hermes 是 CLI 工具**，不实现 IDE 弹窗、"每分钟不超一次点击"等体感约束
2. **--gated 是可选参数**，默认关闭。L1 报告模式不需要 gated，L2/L3 建议开启
3. **暂停机制**：每轮结束后如果未触发停止规则，设置 NEEDS_HUMAN 状态，等待 `hermes loop resume` 继续
4. **不替代停止规则**：gated 只在"本该继续"时暂停；如果停止规则触发，仍然停止

### 何时不使用 gated

- L1_REPORT 阶段（只报告不修改，无风险）
- 简单的 knowledge-hygiene 扫描（只读操作）
- 测试已全绿且无 regression 风险的场景

---

## 完成任务的硬性规则

### 规则 1：修复后必须立即 commit + push

**根因教训**：本地 commit 未 push 时，环境重置（fresh clone）会丢失所有工作。`git fetch` 还会用旧的远程状态覆盖本地分支。

**硬性要求**：

```bash
# 1. 验证修复有效
bash scripts/verify-state.sh

# 2. 提交（必须用 -c 指定 identity，避免 git identity 未配置错误）
git add <具体文件>
git -c user.name="Hermes Agent" -c user.email="hermes@agent.dev" commit -m "<message>"

# 3. 立即推送并用脚本校验（不要等"做完所有事再一起推"）
bash scripts/git-push.sh
```

**push 幻觉防护（硬性）**：

- **必须用 `scripts/git-push.sh` 替代裸 `git push`**——脚本把 push + `ls-remote` 校验绑成原子操作，SHA 不一致就非零退出
- **根因**：模型 `git push` 后可能没读到 stderr，或脑补成功 hash，实际远端没收到。唯一可信源是 `git ls-remote` 返回的远端 SHA
- **禁止行为**：push 后只看 stdout 就报告"已推送"，必须跑校验
- **校验失败时**：不得报告成功，必须重试或向用户报告失败原因
- 如因特殊原因用了裸 `git push`，必须立即手动执行 `git ls-remote origin trae/agent-glOxQF` 与 `git rev-parse HEAD` 对比，两者必须一致

### 规则 2：不要用 `git add .` 或 `git add -A`

- 用 `git add <具体文件>` 添加文件，避免误提交 `.env`、缓存、临时文件
- 提交前用 `git status` 确认暂存内容

### 规则 3：commit message 必须说明"为什么"

- 不是"修改了 X"，而是"修复了 X 导致的 Y 问题"
- 包含根因分析（一句话）和验证方式

---

## 避免长链路压缩导致结果未返回

**根因教训**：fix → verify → commit → push 链路太长时，context 会被压缩，最终总结可能未返回给用户，让用户误以为"任务没完成"。

### 策略 1：分阶段提交，每阶段独立 push

不要等所有修改完成后一次性提交。每完成一个独立的修复单元就提交+推送：

```
修复单元 1 → commit + push → 修复单元 2 → commit + push → ...
```

这样即使会话中途被压缩或中断，已完成的工作也已持久化。

### 策略 2：优先使用并行工具调用

独立的操作（如读多个文件、运行多个验证命令）用并行工具调用，减少串行等待。

### 策略 3：简洁输出

- 不要在回复中重复诊断过程（除非用户问）
- 用脚本输出代替手工罗列验证结果
- 链接到文件而非内联大段代码

---

## 项目分支约定

- **工作分支**：`trae/agent-glOxQF`
- **主分支**：`main`（只接受合并，不直接开发）
- **远程**：`origin`（GitHub: hpj360/Hermes）

### "推送到 git" 的含义（用户约定）

> 用户原话："以后我说推送到git都是指main；合并到main"

- **"推送 / push 到 git"** = `git checkout main && git merge --no-ff trae/agent-glOxQF && git push origin main`
- 工作分支本地提交后**不要**直接 `git push origin trae/agent-glOxQF`；改用合并到 main 的方式
- 单一目标：保持 main 是唯一对外可见的稳定分支
- 仍然用 `scripts/git-push.sh` 替代裸 `git push`，因为它绑定 ls-remote 校验，防 push 幻觉
- 工作分支本身保留在本地（不删除），方便后续在此基础上继续开发

Fresh clone 后必须运行 `bash scripts/setup-tracking.sh` 配置 `trae/agent-glOxQF` 的远程跟踪，否则 `git status` 无法正确显示同步状态。

---

## 脚本说明

| 脚本 | 用途 | 何时运行 |
|------|------|---------|
| `scripts/setup-tracking.sh` | 修复 fresh clone 后的 refspec 盲点 | 新会话开始时（幂等） |
| `scripts/verify-state.sh` | 一键验证 git 同步 + tests + ruff + 关键文件 | 每次需要判断"任务是否完成"时 |
| `scripts/git-push.sh` | push + ls-remote 校验原子化，防 push 幻觉 | 每次 commit 后推送时（替代裸 `git push`） |

三个脚本都**不依赖 git refspec**，在 fresh clone 环境中也能正确工作。

---

## 工作原则（持久化在 knowledge/working-principles.md）

1. **从第一性原理出发**：解决问题/修 BUG/设计架构时，先回到本质约束与基本事实，拆解假设再推导方案，不从既有做法或惯例出发。
2. **复杂任务后多 Agent 对抗性审查**：完成复杂任务后，开启多个独立角色 Agent 从反方视角质疑结论、复现验证、寻找边界与反例。审查发现的问题必须回溯修复，不得带病交付。

详见 [knowledge/working-principles.md](file:///workspace/knowledge/working-principles.md)。
