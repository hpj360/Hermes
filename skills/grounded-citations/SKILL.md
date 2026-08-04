---
name: "grounded-citations"
description: "Verify that every claim in a research report has a traceable, verifiable source. Distinguish 'sounds right' from 'provably sourced'. Use when user needs fact-checking, citation verification, or grounded research. 适用于用户提到'引文验证''事实核查''来源验证''citation''fact-check'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "grounded citations"
  - "引文验证"
  - "事实核查"
  - "来源验证"
  - "citation"
  - "fact-check"
---

# Grounded Citations

确保研究报告中每个论断都有可验证的来源。区分 "听起来对" 与 "可证明有据"。

适配自 Hermes Agent v0.20.0 的 grounded-citations 技能（保留引文逐句验证 +
事实核查模式，适配为 Hermes 研究类 loop 的验证层）。

## 在 Hermes 中的角色

这是研究类 loop 的验证层：
- research skill 产出研究报告
- summarize skill 提取摘要
- **本 skill 验证报告中的每个 claim 都有可验证来源**

可作为 `multi-perspective` loop pattern 中 synthesizer 的验证步骤。

## Process

### 1. 收集 claims
从输入文档中提取所有事实性论断（claims）：
- 数字/统计数据
- 因果关系陈述
- 引用他人观点
- 技术声明（"X 支持 Y"、"Y 已废弃"等）
- 排除：纯观点、修辞性陈述、上下文背景

每个 claim 记录：
- claim 文本
- 所在位置（段落/行号）
- 声称的来源（如有引用）

### 2. 逐句验证
对每个 claim，与声称的来源进行**逐句比对**：
- 访问来源 URL 或文档
- 在来源原文中搜索与 claim 对应的段落
- 比对语义：claim 是否忠实于来源原文

验证结果三态：
| 结果 | 含义 | 标记 |
|------|------|------|
| **verified** | 来源原文明确支持此 claim | ✅ |
| **refuted** | 来源原文与此 claim 矛盾 | ❌ |
| **unverifiable** | 无法访问来源 / 来源中找不到对应内容 | ⚠️ |

**关键原则**：引文必须与网页真实文本逐句比对，不是模型脑补的。
引用链接必须精确指向证据本身。

### 3. 事实核查模式
当输入是"待核查的说法"而非"研究报告"时，使用事实核查模式：
1. 解析说法中的关键事实点
2. 搜索可信来源（优先官方文档/学术论文/权威新闻）
3. 交叉验证：至少 2 个独立来源确认
4. 输出三类结果：
   - **站得住**：多个独立来源支持
   - **站不住**：来源矛盾或反驳
   - **无法验证**：找不到足够来源

### 4. 生成验证报告
输出结构化报告：

```markdown
## 引文验证报告

### 摘要
- 总 claims 数：N
- ✅ 已验证：X (XX%)
- ❌ 已反驳：Y (XX%)
- ⚠️ 无法验证：Z (XX%)

### 详细结果

#### Claim 1: "..."
- 状态：✅ 已验证
- 来源：[链接](url)
- 来源原文："..."（逐句引用）
- 验证说明：claim 忠实于来源

#### Claim 2: "..."
- 状态：❌ 已反驳
- 来源：[链接](url)
- 来源原文："..."
- 验证说明：来源实际说的是...，与 claim 矛盾

#### Claim 3: "..."
- 状态：⚠️ 无法验证
- 原因：来源 URL 无法访问 / 来源中未找到对应内容

### 建议
- 修改 Claim 2 的表述为...
- 为 Claim 3 补充可访问的来源
```

## Completion criteria
- [ ] 所有 claims 已提取并记录
- [ ] 每个 claim 有明确的验证状态（verified/refuted/unverifiable）
- [ ] verified 的 claim 附带来源原文引用
- [ ] refuted 的 claim 说明矛盾点
- [ ] unverifiable 的 claim 说明原因
- [ ] 验证报告结构化输出

## Related skills
- **research**: 源码研究。产出研究报告后，可用本 skill 验证报告中的 claims。
- **summarize**: 摘要提取。本 skill 不做摘要，只做验证。
- **brave-search** / **tavily-search**: 搜索来源。事实核查模式需要搜索可信来源时使用。
