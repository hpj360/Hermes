# Code Review: prototype-validator

> **审阅对象**: `skills/prototype-validator/` (4 个 Python 脚本)
> **审阅时间**: 2026-07-23
> **审阅者**: Hermes Agent
> **关联 commit**: 13e0baa
> **关联测试**: tests/skills/prototype_validator/test_prototype_validator.py (2 cases)

## Verdict: ⚠ FIX P1 (1 P1 / 1 P2 / 0 P0)

## P0 阻塞：无

无阻塞项。

## P1 必须修

### P1-1: 4 维度评分权重未文档化，run_all.py 魔法数

**位置**: `scripts/run_all.py:60-66`

**问题**: 4 维度权重（a11y 0.30, perf 0.30, visual 0.20, interaction 0.20）硬编码且无文档说明理由。

**建议**: 提取为模块顶部常量 + 注释说明为什么 perf 和 a11y 各 0.30（性能和无障碍是 P0 问题，权重应高）。

## P2 可改进

### P2-1: mock 模式下的 interaction score 固定 75，可能误导

**位置**: `scripts/run_all.py` run_a11y / run_visual / run_perf

**问题**: mock 模式未跑真实 axe-core / Lighthouse / Playwright，所有维度返回固定 mock 值（如 interaction 75）。

**建议**: 在 mock 报告中标明 `mock: true` 和"未实际执行"，避免误判为真实评分。

## 亮点

- ✅ 4 维度评分体系（a11y/visual/perf/interaction）
- ✅ A/B/C/D/F 5 档 grade
- ✅ mock 模式可在无 Playwright/Lighthouse 环境跑
- ✅ JSON 报告结构清晰
- ✅ 单元测试 2 cases 验证 mock 模式

## 复杂度评估

- **代码行数**: ~370 行
- **依赖**: 可选（Playwright / axe-core / Lighthouse）
- **可维护性**: 中（魔法数需注释）
- **AI 友好度**: 中（mock 值需明示）
