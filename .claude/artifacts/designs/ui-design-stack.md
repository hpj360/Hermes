---
title: UI/Design Stack 9 项能力补齐
status: ALIGNED
created: 2026-07-23
updated: 2026-07-23
author: Hermes Agent
slug: ui-design-stack
related_knowledge: knowledge/ui-design-stack.md
related_manifest: manifest.json (v0.4.0)
---

# UI/Design Stack 9 项能力补齐 — Spec

## TL;DR

为 Hermes 项目补齐 **9 项 UI/设计相关的 Skill**，分 5 层架构，覆盖从设计稿源 → 选型 → Token → 验证 → 视觉回归 → 差异化设计语言的完整链路。让 Agent 在做 UI 工作时有可量化的标准、可复用的工具、可比较的基线。

## 1. Problem（要解决什么问题）

| 痛点 | 现状 | 影响 |
|------|------|------|
| AI 生成的 UI 容易有"AI 味" | 紫蓝渐变 + Inter 字体 + 卡片化 | 视觉质量不稳定、用户感知"模板感" |
| Figma 设计稿与代码脱节 | 设计改一次，代码再改一次 | 设计师和前端摩擦成本高 |
| Design Token 多端不一致 | web 改一遍，iOS 改一遍，Android 再改一遍 | 同一品牌 5 端不统一 |
| 组件库选型靠拍脑袋 | shadcn vs Ant vs Mantine 凭感觉 | 选错后迁移成本巨大 |
| 不知道新组件对 a11y/性能影响 | 上线才知道 | 紧急返工、客户投诉 |
| 视觉回归靠人眼 | 经常被 PR 漏掉 | 微小 UI bug 流入生产 |
| 缺少差异化设计语言 | 全是 Material/Ant 默认风 | 产品同质化 |
| 设计规范无法被 Skill 复用 | 每写一个新 Skill 都从头开始 | 设计资产无法沉淀 |

## 2. Goal（成功标准）

- 9 项 Skill 全部可独立 CLI 调用，通过率 ≥ 95%
- Token 多端产物（web/iOS/Android/Flutter/Compose）颜色/字号/间距 100% 一致
- UI 反模式扫描能在 10s 内完成单页代码审计
- Storybook 视觉回归能跑通 Figma → Storybook → Chromatic 闭环
- 任何 Skill 改动后，pytest 测试套件自动捕获

## 3. Solution（5 层架构）

```
L5 差异化: liquid-glass-builder
       (Apple WWDC 2025 Liquid Glass Web/iOS 双端)
       ↓
L4 验证闭环: prototype-validator, storybook-chromatic
       (4 维度验证 + 视觉回归)
       ↓
L3 元能力: design-spec-skill-creator
       (设计规范 Markdown → 可复用 Skill 包)
       ↓
L2 同步+选型: style-dictionary-sync, component-library-selector
       (DTCG 多端同步 + 13 库加权评分)
       ↓
L1 基础: figma-reader, ui-design-system, ui-review-checklist
       (Figma REST API + 6 类 Token + 13 类反模式)
```

### 3.1 L1 基础（必须先有）

- **figma-reader**：Figma REST API 4 端点封装（file/nodes/images/components）
- **ui-design-system**：6 类 Token（color/font/space/radius/shadow/motion）+ 多端生成
- **ui-review-checklist**：13 类 AI 味反模式 + 13 项 a11y + 综合评分

### 3.2 L2 同步+选型

- **style-dictionary-sync**：DTCG 标准 8 端产物（CSS/SCSS/JS/TS/Swift/Android/Flutter/Compose）
- **component-library-selector**：13 库 × 8 维度加权评分，5 个场景预设

### 3.3 L3 元能力

- **design-spec-skill-creator**：从设计规范 Markdown 提取 tokens/components/patterns/principles，生成可复用 Skill 包

### 3.4 L4 验证闭环

- **prototype-validator**：4 维度（a11y/visual/perf/interaction）评分系统
- **storybook-chromatic**：Figma → Storybook → Chromatic 视觉回归

### 3.5 L5 差异化

- **liquid-glass-builder**：Apple WWDC 2025 Liquid Glass 跨 Web/iOS 双端实现

## 4. Acceptance Criteria（验收标准）

### AC-1：每项 Skill 至少 1 个 CLI 主入口

| Skill | CLI | 测试 |
|-------|-----|------|
| figma-reader | `read_file.py / read_nodes.py / export_images.py` | ✅ |
| ui-design-system | `validate.py / generate_css.py / audit.py` | ✅ |
| ui-review-checklist | `scan.py / score.py` | ✅ |
| style-dictionary-sync | `sync.py --platforms` | ✅ |
| component-library-selector | `select.py / compare.py` | ✅ |
| design-spec-skill-creator | `from_markdown.py / package_skill.py` | ✅ |
| prototype-validator | `run_all.py` | ✅ |
| storybook-chromatic | `init_storybook.py / sync_figma_to_story.py` | ✅ |
| liquid-glass-builder | `web_to_ios.py` | ✅ |

### AC-2：所有 Skill 通过单元测试

- 9 个 Skill 至少 5 个 pytest test cases
- 全测试套件 pytest tests/ 191+ passed
- ruff 检查通过

### AC-3：manifest.json 注册所有 9 个 Skill

- skills 数组从 23 → 32
- knowledge 数组新增 `ui-design-stack.md`
- 顶层 `ui_design_layer` 字段描述 5 层关系
- version v0.3.0 → v0.4.0

### AC-4：knowledge/ui-design-stack.md 落地

- 9 项能力的协作流程
- 演进路径（v0.4.0 → v1.0.0）
- 与 Hermes 主体的关系

## 5. Out of Scope（不做）

- 不替代设计师（出图、设计探索）
- 不做 3D/动效（仅静态材质）
- 不在不支持 backdrop-filter 的老浏览器上工作（降级但无视觉增强）
- 不在性能敏感场景下使用 Liquid Glass（最多 3 个 backdrop-filter）

## 6. Open Questions

无。所有需求通过 AskUserQuestion 已确认：
- ✅ 全部 9 项都做
- ✅ Figma REST API 封装（不依赖 figma-py 等第三方库）
- ✅ 结合最佳实践方案推进（Apple HIG + Material 3 Expressive + DTCG）

## 7. Plan

详见 `.claude/artifacts/plans/ui-design-stack.md`

## 8. Status

- `DRAFT` → `ALIGNED` → `IMPLEMENTED`（已落地，已推送远端 commit `13e0baa`）
