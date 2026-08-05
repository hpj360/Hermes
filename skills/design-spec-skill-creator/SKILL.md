---
name: design-spec-skill-creator
description: 把团队 UI 设计规范（Notion 页面 / Figma 文件 / 本地 Markdown / PDF）转成可分发的 Skill。提取 tokens / components / patterns / principles，自动生成标准 SKILL.md 骨架。触发场景：用户说"把我们的设计规范做成 skill""从 Figma 库生成 skill""从 Notion 设计文档生成 skill""给团队沉淀设计 skill"。
license: Apache-2.0
---

# 设计规范转 Skill 生成器

把任意格式的设计规范（Notion/Figma/Markdown/PDF）转成符合 Hermes 规范的 Skill 包。

## 4 大模板

| 模板 | 文件 | 适用 |
|---|---|---|
| `tokens-template.md` | SKILL.md (token 主导) | 颜色/字体/间距规范 |
| `component-template.md` | SKILL.md (组件主导) | 组件库规范 |
| `pattern-template.md` | SKILL.md (模式主导) | 设计模式 + 反模式 |
| `full-skill-template.md` | SKILL.md (完整) | 完整设计系统 |

## 输入源

- **Notion**：通过 `notion` skill 导出 Markdown
- **Figma**：通过 `figma-reader` skill 提取 token + 组件清单
- **本地 Markdown**：直接读取
- **PDF**：转 Markdown 后读取（依赖 pdftotext）

## 基础用法

```bash
# 1. 从 Notion 页面生成
python3 scripts/from_notion.py \
  --url "https://notion.so/xxx" \
  --output skills/team-design-system/

# 2. 从 Figma 文件生成
python3 scripts/from_figma.py \
  --file-key ABC123 \
  --output skills/team-design-system/

# 3. 从本地 Markdown 生成
python3 scripts/from_markdown.py \
  --input design-spec.md \
  --output skills/team-design-system/ \
  --template tokens

# 4. 打包现有 Skill（验证完整性）
python3 scripts/package_skill.py skills/team-design-system/
```

## 工作流

```
输入源（Notion/Figma/Markdown）
    ↓
内容提取（按 4 类）
  ├── tokens（颜色/字体/间距/阴影）
  ├── components（组件清单 + props）
  ├── patterns（设计模式/最佳实践）
  └── principles（设计原则/反模式）
    ↓
模板填充（4 大模板之一）
    ↓
Skill 包生成
  ├── SKILL.md
  ├── _meta.json
  ├── references/  (可选)
  └── scripts/     (可选)
    ↓
package_skill.py 验证
    ↓
可用 Skill
```

## 提取规则

### Tokens
- 匹配 `color: #FF0000` / `padding: 16px` / `font-size: 14px` 等
- 按值类型分类（color/spacing/typography/...）
- 输出到 `tokens/*.json`

### Components
- 匹配 `## Button` 标题 + 下方属性表格
- 提取 props 列表
- 输出到 `references/components.md`

### Patterns
- 匹配 `### 模式：` 或 `### Pattern:` 标题
- 提取最佳实践 + 代码示例
- 输出到 `references/patterns.md`

### Principles
- 匹配 `## 原则` / `## 反模式` / `## Anti-pattern` 标题
- 提取列表
- 输出到 `references/principles.md`

## 与其他 skill 配合

| Skill | 关系 |
|---|---|
| `notion` | 提供 Notion 页面导出能力 |
| `figma-reader` | 提供 Figma 文件提取能力 |
| `skill-creator` | 本 skill 生成的 Skill 用它打包 |
| `ui-design-system` | tokens 提取后可直接导入 |

## Related skills（边界声明）

- **skill-creator**: 通用 skill 创建/评测工具。本 skill 是**垂直场景专用**（从设计规范生成 skill），skill-creator 是**通用**（适用任何 skill 类型）。组合使用：本 skill 产初稿（SKILL.md 骨架 + tokens/components/patterns/principles）→ skill-creator 跑 evals 评测 + 优化 description。
- **figma-reader**: Figma 资产读取。本 skill 通过 figma-reader 拉 Figma 文件内容。
- **notion**: Notion 页面 API。本 skill 通过 notion 拉 Notion 设计文档。
- **ui-design-system**: Token canonical source。本 skill 提取的 tokens 交给 ui-design-system 规范化（6 类 token 校验）。

## 不适用

- 实时维护的设计规范（生成的是快照，需手动同步）
- 包含 Figma 高级交互的设计稿（建议导出视频或截图）
- 加密 PDF / DRM 文档
