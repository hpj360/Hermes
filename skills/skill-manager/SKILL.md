---
name: skill-manager
description: 管理已安装的 skill 生命周期：列出、安装、同步、卸载、搜索目录。基于 Hermes 的本地 Skill Sync（跨 Agent 目录分发）与 Skill marketplace（安装/打包/目录）机制。
---

# Skill Manager

这个技能用于管理**本机已安装**的 skill。核心机制是两套真实的 Hermes CLI：

- **`hermes skill-sync`**：跨 Agent 目录的同步管理（中心仓库 `skills/` 是唯一可信来源，通过 symlink/copy 分发到 codex/cursor/trae/opencode 等目录）。
- **`hermes skills`**：marketplace（从 registry/git/zip/本地路径安装 skill，打包分发，查看目录）。

> 本技能原文档引用虚构的 `skillhub`/`clawhub` CLI，现已移除。所有操作一律走 `hermes` 命令。

## 功能

- **列出**：`hermes skill-sync status`（含各 Agent 目录同步状态）或 `hermes skills list`
- **安装**：`hermes skills install <name> [--source ...] [--force]`
- **同步**：`hermes skill-sync sync [name]`（把中心改动分发到各 Agent）
- **卸载/取消管理**：`hermes skill-sync remove <name>`
- **搜索目录**：`hermes skills remote`（vendor + 远程 registry 合并目录）
- **纳入/取消管理**：`hermes skill-sync add/remove [--all] [--copy]`
- **Agent 目录**：`hermes skill-sync agents` / `hermes skill-sync add-agent <name> <path>`

## 工作流程

### Step 1: 检测 Hermes CLI 可用性

**CHECKPOINT**: `hermes` 命令是否可用？

```bash
which hermes || ./hermes --help
```

- 仓库内：直接 `./hermes`（零安装入口）。
- pip install 后：直接 `hermes`。
- 两者都不可用：运行 `bash scripts/bootstrap.sh` 引导。

### Step 2: 执行操作

#### 操作 A: 列出 skill 与同步状态

```bash
hermes skill-sync status
# 或只看中心仓库已安装列表
hermes skills list
```

**CHECKPOINT**: 输出是否包含 skill 名与各 Agent 状态（linked/synced/missing/conflict/local_changes/external_changes）？
- 成功：向用户展示列表，重点标注 `conflict` / `external_changes` 这类需人工介入的状态。
- `No skills found`：中心仓库为空，或尚未 `add` 纳管。

#### 操作 B: 搜索目录并安装 skill

```bash
# 查看 registry 目录（vendor + 远程合并）
hermes skills remote

# 安装（默认走 registry；也可指定 --source）
hermes skills install <name>
hermes skills install <name> --source <git-url|local-path|zip-url>
```

**CHECKPOINT**: 安装前安全检查
- [ ] skill 名称是单个路径组件（kebab-case，无 `..`、路径分隔符）
- [ ] 来源可信（官方 registry 或已知仓库）
- [ ] 与当前环境兼容（安装后能加载 SKILL.md）

> 安装只会写入中心仓库 `skills/`。若需分发到各 Agent，安装后执行 `hermes skill-sync add <name>`（见操作 C）。

#### 操作 C: 同步到各 Agent 目录

```bash
# 将 skill 纳入同步管理（symlink 或 copy）
hermes skill-sync add <name>            # symlink（默认，实时同步）
hermes skill-sync add <name> --copy     # copy 模式

# 同步中心改动
hermes skill-sync sync [name]           # name 缺省同步全部
```

**CHECKPOINT**: 冲突保护
- copy 模式下，`conflict`/`external_changes` 会被跳过（不覆盖 Agent 侧用户改动）。
- 遇到 `conflict`：先 `hermes skill-sync status` 定位，人工决策后再处理，不擅自合并。

#### 操作 D: 取消管理 / 卸载

```bash
# 先列出确认
hermes skill-sync status | grep <关键词>

# 取消同步管理（symlink 删除链接 / copy 回写后删中心副本）
hermes skill-sync remove <name>
```

**CHECKPOINT**: 卸载前确认
- 确认 skill 名称正确（避免误删）
- 确认不再被其他 skill 依赖
- `remove` 作用于“同步管理”，不等于删除中心仓库源文件；如需彻底删除中心 `skills/<name>/`，另行说明。

#### 操作 E: 查看 / 管理 Agent 目录

```bash
hermes skill-sync agents                 # 列出已发现的 Agent 目录
hermes skill-sync add-agent <name> <path> # 添加自定义 Agent 目录
```

**CHECKPOINT**: 自定义目录是否纳入发现
- `agents` 输出中自定义项带 `*` 标记。
- 目录不存在时标注 `(missing)`。

### Step 3: 验证结果

**CHECKPOINT**: 操作是否成功？
- 检查退出码（0 成功，1 软失败，2 硬错误）。
- `skill-sync` 的 `--json` 标志可输出机器可读结果（含 `errors` 明细）。

---

## 失败处理流程

### 常见失败场景

| 场景 | 原因 | 处理方式 |
|------|------|---------|
| `hermes` 命令不存在 | 未引导 / 不在 PATH | 仓库内跑 `bash scripts/bootstrap.sh` |
| `skill X not found in central repo` | 中心 `skills/` 无此 skill | 先 `hermes skills remote` 找目录，再 `install` |
| `existing content, skipped` | Agent 目录已有同名内容 | 人工确认后决定是否覆盖，勿擅自删除 |
| `conflict` | 中心与 Agent 双端均有改动 | 用 `status` 定位，人工合并，不自动覆盖 |
| `external_changes` | Agent 侧有本地改动 | copy 模式下 sync 会跳过；人工确认后再处理 |
| 安装 `already installed` | 目标已存在 | 用 `--force` 覆盖（谨慎），或换名 |
| `path outside known agent dirs (skipped)` | 状态文件被污染 | 检查 `.state/skill_sync.json`，修正后重试 |

### 失败时用户通知

```
❌ 同步 skill <name> 失败

原因：
- agent <cursor> 存在本地改动（state=external_changes），copy 模式跳过覆盖

建议：
1. hermes skill-sync status 查看详情
2. 人工确认 cursor 侧改动是否需要保留
3. 保留则不动；要覆盖则先备份后手动同步
```

---

## 反例与黑名单

| 禁止 | 原因 | 替代方案 |
|------|------|---------|
| ❌ 未经确认直接 `remove` | 可能误删正在使用的同步/源 | 先 `status` 列出，让用户确认 |
| ❌ 遇到 `conflict` 擅自合并 | 会覆盖双端改动 | 报告状态，人工决策 |
| ❌ 安装来源不明即执行 | 安全风险 | 校验名称与来源，用官方 registry |
| ❌ 用 `--force` 覆盖中心 skill | 丢失本地修改 | 覆盖前 diff 并备份 |
| ❌ 忽略 `errors` 明细 | 无法定位问题 | 用 `--json` 读取完整 errors |

---

## Related skills（边界声明）

- **find-skills**: 候选 skill **发现**（“世界上有什么 skill”，`npx skills`）。本 skill 是**安装后管理**。标准流程：`find-skills → skill-manager`。
- **skill-creator**: skill 创建/改进。本 skill 关注**已安装** skill 的管理；skill-creator 关注**开发**阶段。