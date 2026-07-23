# Code Review: component-library-selector

> **审阅对象**: `skills/component-library-selector/` (2 个 Python 脚本 + 1 个 libraries.json)
> **审阅时间**: 2026-07-23
> **审阅者**: Hermes Agent
> **关联 commit**: 13e0baa
> **关联测试**: tests/skills/component_library_selector/test_component_library_selector.py (6 cases)

## Verdict: ✅ READY (无 P0 / 0 P1 / 1 P2)

## P0 阻塞：无

无阻塞项。

## P1 必须修

无 P1 项。

## P2 可改进

### P2-1: 评分加权时未做归一化，boost 后可能超过 100

**位置**: `scripts/select.py:33-38`

**问题**: 当 `scenario.boost` 中某维度倍数 > 1（如 ai-coding 的 ai_friendly: 2.0），加权总分会超过 100（如 shadcn/ui 在 ai-coding 场景下得 113.2）。

**建议**: 加权时按 `min(score, 100)` 或在显示中标明"加权分"，与原始分区分。

**实际影响**: 用户看到 113 可能困惑。

## 亮点

- ✅ 13 个候选库覆盖主流（React/Vue + Full/Headless）
- ✅ 8 维度加权（bundle/customization/ts/a11y/coverage/community/docs/ai_friendly）
- ✅ 5 个场景预设（modern-web / enterprise / vue3 / ai-coding / performance）
- ✅ 库对库对比（compare.py）
- ✅ 单元测试 6 cases 验证场景推荐 + 对比

## 复杂度评估

- **代码行数**: ~110 行
- **依赖**: 零
- **可维护性**: 高（数据驱动）
- **AI 友好度**: 高（JSON 数据易于扩展）
