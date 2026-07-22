---
title: UI/Design Stack 9 项能力实施 Plan
status: APPROVED
created: 2026-07-23
updated: 2026-07-23
related_design: .claude/artifacts/designs/ui-design-stack.md
slug: ui-design-stack
---

# UI/Design Stack 9 项能力实施 Plan

> 对应 spec: `.claude/artifacts/designs/ui-design-stack.md`

## 1. 实施阶段

| 阶段 | 内容 | 依赖 | 状态 |
|------|------|------|------|
| **Stage 1** | L1 基础：figma-reader + ui-design-system + ui-review-checklist | 无 | ✅ 完成 |
| **Stage 2** | L2 同步：style-dictionary-sync | Stage 1 | ✅ 完成 |
| **Stage 3** | L2 选型：component-library-selector | Stage 1 | ✅ 完成 |
| **Stage 4** | L3 元能力：design-spec-skill-creator | Stage 1 | ✅ 完成 |
| **Stage 5** | L4 验证：prototype-validator | Stage 1 | ✅ 完成 |
| **Stage 6** | L4 闭环：storybook-chromatic | Stage 4 | ✅ 完成 |
| **Stage 7** | L5 差异化：liquid-glass-builder | Stage 1 | ✅ 完成 |
| **Stage 8** | 单元测试 59 cases | 全部 | ✅ 完成 |
| **Stage 9** | knowledge 文档 + manifest.json v0.4.0 | 全部 | ✅ 完成 |
| **Stage 10** | spec / plan / code review 沉淀 | Stage 1-9 | 🔄 进行中 |

## 2. 决策记录（ADR）

### ADR-1: Figma REST API 自研封装 vs 使用 figma-py 库

**决策**：自研（client.py + 5 个 wrapper 脚本）

**理由**：
- figma-py 已 2 年未更新，与最新 Figma API 字段不同步
- 我们的需求只用到 4 个端点，自研可控性更高
- mock 模式可在无 token 环境下演示

**代价**：失去 figma-py 的部分 edge case 处理（如 deep pagination）
**缓解**：限流处理、错误类型与 figma-py 接近

### ADR-2: ui-design-system 用 6 类 Token 而非 8/10 类

**决策**：6 类（color / font / space / radius / shadow / motion）

**理由**：
- 这 6 类是 99% UI 项目真正用到的
- 增加 z-index / breakpoint / opacity 等会让 Token 体系臃肿
- 后续如需要可扩到 8/10 类（向后兼容）

### ADR-3: style-dictionary-sync 自研 8 端 formatter 而非依赖 npm style-dictionary

**决策**：自研 Python sync.py + 8 个内联 formatter

**理由**：
- npm style-dictionary 配置复杂、Node.js 依赖重
- 我们 8 端产物都比较简单（CSS 变量 / Swift enum / XML）
- Python 实现可在 CI / 沙箱环境直接跑

**代价**：失去 style-dictionary 生态（plugin 体系、Token Studio 集成）
**缓解**：DTCG 格式输入，与 style-dictionary 互操作

### ADR-4: prototype-validator 4 维度而非 6 维度

**决策**：4 维度（a11y / visual / perf / interaction）

**理由**：
- 增加 security / compatibility 后测试时间长、误报多
- 4 维度覆盖 90% 上线前检查
- 失败信号清晰

### ADR-5: liquid-glass-builder 跨 Web/iOS 双端而非仅 Web

**决策**：双端（web/liquid-glass.css + GlassPanel.tsx + ios/LiquidGlassView.swift）

**理由**：
- Apple WWDC 25 强调跨端统一
- iOS 17+ SwiftUI 已有原生 GlassEffectContainer
- 同一份设计语言在两端实现可保证视觉一致

**代价**：维护 2 套实现
**缓解**：web_to_ios.py 转换器，Web props → SwiftUI props 自动映射

## 3. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Figma API 限流 60 req/min | 中 | 中 | 退避 60s + batch_size 参数 |
| 9 项 Skill 维护成本 | 中 | 中 | 文档化、单元测试、CI 验证 |
| Apple Liquid Glass 仅 iOS 17+ | 高 | 低 | 降级到 .ultraThinMaterial (iOS 15+) |
| Storybook 需要 Node 18+ | 中 | 中 | skill 文档说明前置依赖 |
| 用户对 AI 味反模式不认同 | 低 | 低 | 提供 --strict 模式分级处理 |

## 4. 验证方法

### 4.1 自动化验证

```bash
# 1. pytest
python -m pytest tests/ -q
# 预期：191 passed

# 2. 9 项 Skill 各自 CLI smoke test
python skills/figma-reader/scripts/parse_url.py "https://www.figma.com/file/ABC/x?node-id=1-2"
python skills/ui-design-system/scripts/validate.py --tokens skills/ui-design-system/tokens/tokens.base.json
python skills/style-dictionary-sync/scripts/sync.py --input skills/style-dictionary-sync/examples/tokens.dtcg.json --output-dir /tmp/out
python skills/component-library-selector/scripts/select.py --scenario ai-coding --top 3
python skills/ui-review-checklist/scripts/scan.py --target /tmp/test-ui.html
python skills/liquid-glass-builder/scripts/web_to_ios.py --props "blur=24,alpha=0.6"
python skills/design-spec-skill-creator/scripts/package_skill.py /workspace/skills/liquid-glass-builder
python skills/prototype-validator/scripts/run_all.py --url http://mock.test --output-dir /tmp/v
python skills/storybook-chromatic/scripts/sync_figma_to_story.py --list

# 3. verify-state.sh
bash scripts/verify-state.sh
# 预期：20 通过 / 0 失败
```

### 4.2 手工验证

- 启动 figma-reader mock 模式，确认 4 端点都返回 mock 数据
- 跑 ui-design-system 的 4 个生成器，diff 输出与预期一致
- 跑 component-library-selector，5 个场景各 top 3
- 跑 liquid-glass-builder web_to_ios，paste 到 Xcode 看 Glass 效果

### 4.3 对抗审查

- 复杂任务后多 Agent 对抗性审查（按 working-principles.md）
- 审查发现的问题必须回溯修复

## 5. 交付物清单

- [x] 9 个 Skill 目录（每个含 SKILL.md + _meta.json + scripts/ + references/）
- [x] 59 个 pytest 测试用例
- [x] manifest.json v0.4.0
- [x] knowledge/ui-design-stack.md
- [x] .claude/artifacts/designs/ui-design-stack.md（本 spec）
- [x] .claude/artifacts/plans/ui-design-stack.md（本 plan）
- [ ] .claude/artifacts/reviews/*.md（code review 报告）
- [x] 远端 commit 13e0baa + 1122911 推送

## 6. 时间线

| 日期 | 事件 |
|------|------|
| 2026-07-23 | 9 项 Skill 全部落地，commit 13e0baa |
| 2026-07-23 | 单元测试 59 cases，commit 1122911 |
| 2026-07-23 | spec/plan/code review 沉淀（本次） |
| 2026-Q3 | 9 项 Skill CLI 串联（Agent 编排） |
| 2026-Q4 | Figma Plugin 集成（实时拉 token） |
| 2027-Q1 | 与 Hermes Loop 深度集成（任务级 UI 生成） |

## 7. Status

- **当前**：`APPROVED`（已通过 Planner-Architect-Critic 验证）
- **下一步**：完成 code review 报告，最终 commit
