# Code Review: storybook-chromatic

> **审阅对象**: `skills/storybook-chromatic/` (3 个 Python 脚本 + 2 个模板)
> **审阅时间**: 2026-07-23
> **审阅者**: Hermes Agent
> **关联 commit**: 13e0baa
> **关联测试**: tests/skills/storybook_chromatic/test_storybook_chromatic.py (6 cases)

## Verdict: ✅ READY (无 P0 / 0 P1 / 1 P2)

## P0 阻塞：无

无阻塞项。

## P1 必须修

无 P1 项。

## P2 可改进

### P2-1: sync_figma_to_story.py 必须传真实 Figma token，无 mock 模式

**位置**: `scripts/sync_figma_to_story.py`

**问题**: 同步脚本依赖 Figma API，未提供 mock 模式，单元测试只能测内部 `_to_pascal_case` 等工具函数。

**建议**: 借鉴 figma-reader 的 mock 模式，提供 `--mock` 参数走本地 fixture。

## 亮点

- ✅ Figma → Storybook → Chromatic 闭环设计
- ✅ CSF 3.0 格式（Meta + StoryObj）
- ✅ 提供完整模板（storybook.config.js + chromatic.config.json）
- ✅ 工具函数（_to_pascal_case / _to_camel_case / generate_component_stub）独立可测
- ✅ 单元测试 6 cases 覆盖工具函数 + 模板存在性

## 复杂度评估

- **代码行数**: ~250 行
- **依赖**: requests + 可选 npx chromatic
- **可维护性**: 高（CSF 3.0 标准化）
- **AI 友好度**: 高（生成代码 LLM 易理解）
