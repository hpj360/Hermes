# Skill Sync：多 Agent 时代的 Skill 管理方案

> 来源：阿里云云原生《别再手动复制 Skill 了：多 Agent 时代的 Skill 管理方案》（作者：刘鹏/墨松）
> 融合：Hermes 项目已实现 Local mode 版本的 Skill Sync

---

## 一、核心问题：Skill 碎片化

在多 Agent 并行使用的时代，开发者面临一个普遍痛点：

- **工具可以无缝切换，Skill 无法自动跟随**
- Codex 中更新的 Skill，Claude Code 里仍是旧版
- Cursor 目录下可能并存同名但内容迥异的副本
- 手动复制效率低、容易出错、版本混乱
- 碎片化版本管理消耗心力，降低效率

**反模式**：
- Git submodule / Monorepo：改个 Prompt 还要走 commit/push/pull，太重
- Syncthing 等通用同步工具：只懂文件不懂 Skill 语义，双向修改易产生覆盖灾难
- LangSmith 等 Prompt 管理平台：为 LLM 应用开发设计，不管本地 Agent 配置文件

**核心洞察**：需要的是"改一处就全部生效、且随时知道哪份是最新"的闭环方案。

---

## 二、核心理念：单一可信来源（Single Source of Truth）

Skill Sync 的核心思想可以用一句话概括：

**把 Skill 收敛到一个中心仓库，再按需分发给各个 Agent。**

具体原则：
1. **只维护一份中心仓库**：统一存放 Skill 内容和同步状态
2. **改一处，全部生效**：默认软链接方式关联各 Agent 目录
3. **状态随时可查**：远端/本地/冲突状态一目了然
4. **保守的冲突策略**：不擅自替用户做选择，冲突时明确指定来源
5. **渐进式采用**：先 Local mode 收拢本机，需要时再升级 Registry mode

---

## 三、两种模式

### 3.1 Local mode（本机轻量同步，零服务依赖）

适合个人开发者，先把本机多个 Agent 的 Skill 统一起来。

- **本地中心仓库**：Hermes 的 `skills/` 目录作为单一信源
- **软链接默认**：各 Agent 目录通过 symlink 指向中心仓库，改一处全局生效
- **复制备选**：环境不支持软链接时可切换到复制模式，由 CLI 负责同步
- **自动发现**：自动识别 Codex、Claude Code、Cursor、Qoder、Kiro、Lingma、Trae 等常见 Agent 目录
- **零依赖**：无需部署任何服务，开箱即用

### 3.2 Registry mode（远端 Registry，跨设备/团队）

适合团队协作或多设备场景，目前 Hermes 已预留接口，可后续对接 Nacos AI Registry。

- **可视化管理**：控制台浏览、搜索、查看 Skill
- **版本治理**：草稿、审核、发布、回滚、label
- **跨设备同步**：多设备从同一 Registry 拉取
- **双向流通**：远端 ↔ 本地双向同步
- **Profile 隔离**：不同 profile 维护独立 Skill repo，不互相覆盖

---

## 四、Skill 状态模型

每个被管理的 Skill 都有明确的状态，可通过 `hermes skill-sync status` 查看：

| 状态 | 含义 | 下一步 |
|------|------|--------|
| **linked** | 已通过软链接关联到中心仓库（推荐） | 无需操作 |
| **synced** | 已通过复制方式同步 | 无需操作 |
| **local_changes** | 中心仓库有改动，尚未同步到 Agent | `hermes skill-sync sync` |
| **external_changes** | Agent 目录有改动，与中心不一致 | `hermes skill-sync resolve` 选择版本 |
| **conflict** | 中心和外部同时改了，冲突 | `hermes skill-sync resolve --source <source>` |
| **missing** | 中心仓库副本缺失 | `hermes skill-sync sync` 恢复 |
| **unmanaged** | 尚未纳入 Skill Sync 管理 | `hermes skill-sync add <skill>` |

---

## 五、日常工作流

### 5.1 快速上手

```bash
# 1. 查看当前状态
hermes skill-sync status

# 2. 查看发现了哪些 Agent 目录
hermes skill-sync agents

# 3. 批量纳入管理（推荐软链接模式）
hermes skill-sync add --all

# 4. 或者逐个添加
hermes skill-sync add wechat-reader
hermes skill-sync add douyin-reader --copy  # 使用复制模式
```

### 5.2 日常使用

```bash
# 日常只需要看一个命令
hermes skill-sync status

# 中心仓库改了内容后，同步到所有 Agent
hermes skill-sync sync

# 只同步特定 Skill
hermes skill-sync sync wechat-reader
```

### 5.3 处理冲突

遇到冲突时（状态显示 conflict），**策略默认保守——不会擅自替你做选择**：

```bash
# 查看冲突情况
hermes skill-sync status

# 选择保留中心仓库版本
hermes skill-sync resolve my-skill --source central

# 选择保留某个 Agent 的版本
hermes skill-sync resolve my-skill --source codex
```

### 5.4 添加自定义 Agent 目录

```bash
# 添加你的自定义 Agent
hermes skill-sync add-agent my-agent ~/my-agent/skills
```

### 5.5 取消管理

```bash
# 取消单个 Skill 的同步（会保留各 Agent 的副本）
hermes skill-sync remove wechat-reader

# 取消全部
hermes skill-sync remove --all
```

---

## 六、使用案例

### 案例一：个人周报 Skill（Local mode）

**问题**：每天在多个 Agent 处理任务——Codex 改代码、Claude 查日志、Cursor 补测试，工作记录散在不同对话，周五整理周报痛苦。

**解决**：
1. 在 Hermes 中心仓库创建 `weekly-report` Skill
2. `hermes skill-sync add weekly-report`
3. 所有 Agent 通过软链接共享同一份 Skill
4. 在 Codex 里调整周报字段，Claude/Cursor 立即看到更新
5. 不需要服务端，私人工作记录不会同步出去

### 案例二：团队文档格式规范（Registry mode）

**问题**：团队文档由不同人/设备/Agent 生成，标题层级、参数表、评审清单格式不统一，靠口头提醒不稳定。

**解决**（Registry mode，未来对接）：
1. 团队把文档格式规范沉淀为 `doc-format` Skill
2. 放入 Nacos AI Registry 统一管理
3. 团队成员、不同设备通过 Sync 拉取同一套规范
4. 规范更新只维护 Registry 一份，全团队同步生效

---

## 七、设计原则总结

| 原则 | 说明 |
|------|------|
| **单一信源** | `skills/` 目录是唯一可信来源 |
| **默认软链接** | 零开销实时同步，改一处全局生效 |
| **状态可见** | 一个 `status` 命令看清所有 Skill 状态 |
| **保守冲突** | 不擅自合并，用户明确指定来源才执行 |
| **渐进采用** | 先 `add --all` 收拢本机，后续再考虑 Registry |
| **安全移除** | remove 时先把内容复制回各 Agent，再解除同步 |
| **自动发现** | 常见 Agent 目录自动识别，也可手动添加 |

---

## 八、Hermes CLI 命令参考

```bash
# 状态总览（日常最常用）
hermes skill-sync status

# 列出发现的 Agent 目录
hermes skill-sync agents

# 添加 Skill 到同步管理
hermes skill-sync add <skill> [--source <agent>] [--copy]
hermes skill-sync add --all [--copy]

# 取消同步
hermes skill-sync remove <skill>
hermes skill-sync remove --all

# 执行同步（推送中心仓库改动到 Agent）
hermes skill-sync sync [<skill>]

# 解决冲突
hermes skill-sync resolve <skill> --source central|<agent-name>

# 添加自定义 Agent 目录
hermes skill-sync add-agent <name> <path>
```

---

**金句**：**"Agent 可以换，Skill 不应该跟着散。让 Skill 有一份可信来源。"**
