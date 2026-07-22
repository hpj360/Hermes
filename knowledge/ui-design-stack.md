# UI/Design Stack 能力图谱

> **核心问题**：当 Agent 需要做 UI/设计相关工作时，如何让"做出来的 UI"质量稳定可量化？

本文档定义 9 项 UI/设计相关 Skill 的分层架构，覆盖从设计稿源 → 选型 → Token → 验证 → 视觉回归 → 差异化设计语言的完整链路。

## 1. 为什么需要这 9 项

| 痛点 | 现状 | 9 项能力如何解 |
|------|------|---------------|
| AI 生成的 UI 容易有"AI 味" | 紫蓝渐变 + Inter + 卡片化 | `ui-review-checklist` 13 类反模式扫描 |
| Figma 设计稿与代码脱节 | 设计改一次，代码再改一次 | `figma-reader` + `style-dictionary-sync` 自动同步 |
| Design Token 多端不一致 | web 改一遍，iOS 改一遍，Android 再改一遍 | `ui-design-system` 6 类 token + `style-dictionary-sync` 8 端产物 |
| 选型靠拍脑袋 | shadcn vs Ant vs Mantine 凭感觉 | `component-library-selector` 13 库 × 8 维度加权评分 |
| 不知道新组件对 a11y/性能影响 | 上线才知道 | `prototype-validator` 4 维度验证 |
| 视觉回归靠人眼 | 经常被 PR 漏掉 | `storybook-chromatic` 云端回归 |
| 缺少差异化设计语言 | 全是 Material/Ant 默认风 | `liquid-glass-builder` Apple WWDC25 |
| 设计规范无法被 Skill 复用 | 每写一个新 Skill 都从头开始 | `design-spec-skill-creator` 从 Markdown 生成 Skill |

## 2. 5 层架构

```
┌─────────────────────────────────────────────────────────────┐
│  L5 差异化: liquid-glass-builder                            │
│     Apple WWDC 2025 Liquid Glass 跨 Web/iOS 双端实现        │
├─────────────────────────────────────────────────────────────┤
│  L4 验证闭环: prototype-validator, storybook-chromatic      │
│     4 维度验证 (a11y/visual/perf/interaction) + 视觉回归     │
├─────────────────────────────────────────────────────────────┤
│  L3 元能力: design-spec-skill-creator                       │
│     设计规范 Markdown → 可复用 Skill 包                     │
├─────────────────────────────────────────────────────────────┤
│  L2 同步+选型: style-dictionary-sync, component-library-selector │
│     DTCG 多端同步 + 13 库加权评分                           │
├─────────────────────────────────────────────────────────────┤
│  L1 基础: figma-reader, ui-design-system, ui-review-checklist │
│     Figma REST API + 6 类 Token + 13 类反模式                │
└─────────────────────────────────────────────────────────────┘
```

### L1 基础（3 项，必须先有）

- **figma-reader**：Figma REST API 封装，4 端点读文件/节点/图片/组件
- **ui-design-system**：6 类 Token（color/font/space/radius/shadow/motion）+ 多端生成
- **ui-review-checklist**：13 类 AI 味反模式 + 13 项 a11y + 综合评分

### L2 同步+选型（2 项）

- **style-dictionary-sync**：DTCG 标准，8 端产物（CSS/SCSS/JS/TS/Swift/Android/Flutter/Compose）
- **component-library-selector**：13 库 × 8 维度加权评分，5 个场景预设

### L3 元能力（1 项）

- **design-spec-skill-creator**：从设计规范 Markdown 提取 tokens/components/patterns/principles，生成可复用 Skill 包

### L4 验证闭环（2 项）

- **prototype-validator**：4 维度（a11y/visual/perf/interaction）评分系统
- **storybook-chromatic**：Figma → Storybook → Chromatic 视觉回归

### L5 差异化（1 项）

- **liquid-glass-builder**：Apple WWDC 2025 Liquid Glass 跨 Web/iOS 双端

## 3. 协作流程示例

### 流程 A：启动新项目

```
1. component-library-selector → 选 shadcn/ui
2. ui-design-system → 定义 6 类 Token
3. figma-reader → 拉 Figma 文件做参考
4. style-dictionary-sync → 生成多端 token
5. 业务开发
6. prototype-validator → 提交前自检
7. storybook-chromatic → 视觉回归
```

### 流程 B：改造旧项目

```
1. ui-review-checklist → 发现 13 类反模式
2. ui-design-system → 引入 Token 系统
3. style-dictionary-sync → 与现有 CSS 变量共存
4. component-library-selector → 评估迁移目标库
5. prototype-validator → 改造前后对比
```

### 流程 C：差异化设计

```
1. design-spec-skill-creator → 把 Apple HIG 转 Skill
2. liquid-glass-builder → 在关键页面用 Liquid Glass
3. storybook-chromatic → 验证视觉一致性
```

## 4. 与 Hermes 主体的关系

| 维度 | Hermes | UI/Design Stack |
|------|--------|----------------|
| 抽象层级 | Loop Engineering 引擎 | 具体业务域 |
| 输入 | 用户任务描述 | Figma / 源码 / Token JSON |
| 输出 | 任务执行结果 | 多端 UI 代码 + 验证报告 |
| 复用方式 | Sub-Agent 调用 | CLI 脚本或 Python 模块 |

UI/Design Stack 是 Hermes 在 UI 域的"垂直深耕"，复用 Hermes 的 Loop/Sub-Agent 框架。

## 5. 演进路径

| 阶段 | 时间 | 关键里程碑 |
|------|------|----------|
| v0.4.0 (当前) | 2026-07 | 9 项 Skill 全部具备，单项独立可用 |
| v0.5.0 | 2026-Q3 | 9 项 Skill 之间的 CLI 串联（Agent 编排） |
| v0.6.0 | 2026-Q4 | Figma Plugin 集成（实时拉 token） |
| v1.0.0 | 2027-Q1 | 与 Hermes Loop 深度集成（任务级别 UI 生成） |

## 6. 不做什么

- 不替代设计师（出图、设计探索）
- 不做 3D/动效（仅静态材质）
- 不在不支持 backdrop-filter 的老浏览器上工作（降级但无视觉增强）
- 不在性能敏感场景下使用 Liquid Glass（最多 3 个 backdrop-filter）
