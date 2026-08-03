# Skill 编写词汇表

> 来源：mattpocock/skills `writing-great-skills`，沉淀为 Hermes 项目内 skill 编写的统一词汇与质量标准。
> 适用：编写或审查 `skills/<name>/SKILL.md` 时参考。

## 一、Skill 的本质

Skill 是**带触发条件的 prompt 片段**，不是代码。它的价值在于：
- **Progressive disclosure**：渐进式披露，先给方向，按需深入
- **Composable**：可组合，skill A 可调用 skill B
- **Hackable**：用户可改，不存在"黑盒"

## 二、核心词汇

### 2.1 Progressive Disclosure（渐进式披露）

Skill 不应一次性倾倒所有信息。层次：
1. **Frontmatter description**：一句话告诉调度器何时触发
2. **Body 第一段**：用户看到的第一行，说明 skill 做什么
3. **Process 章节**：执行步骤
4. **Deep dive 章节**：按需深入的细节

反模式：把所有细节放在 frontmatter（调度器读不完）或第一段（用户被淹没）。

### 2.2 Leading Words（引导词）

Frontmatter `description` 的开头决定触发优先级：
- **动词开头**：`Move issues through...` / `Diagnose...` / `Review...` — 明确动作
- **名词开头**：`A discipline for...` / `Two-axis review...` — 描述形态
- 避免：`This skill helps...` / `Use this to...` — 浪费 token

### 2.3 Information Hierarchy（信息层次）

按"用户需要的频率"排列，不是按"逻辑完整性"：
- **高频**：每次调用都需要的（Process 步骤、Completion criteria）
- **中频**：偶尔参考的（Why 章节、反模式）
- **低频**：罕见但关键时需要的（Edge cases、与其他 skill 的关系）

### 2.4 Failure Modes（失败模式）

Skill 必须显式声明"什么时候会失败"：
- 输入不满足前置条件
- 依赖的外部服务不可用
- 用户意图与 skill 能力不匹配

反模式：只写 happy path。

### 2.5 Composability（可组合性）

Skill 应声明它**调用**和**被调用**的关系：
- `调用`：本 skill 在 Process 中会调用哪些其他 skill
- `被调用`：哪些 loop pattern / 上层 skill 会触发本 skill
- `不调用`：显式声明边界，避免 skill 膨胀

## 三、质量检查清单

编写或审查 SKILL.md 时逐项检查：

- [ ] Frontmatter 含 `name` / `description` / `version` / `triggers`
- [ ] `description` 以动词或名词开头，不超过 2 句话
- [ ] `triggers` 含中英文关键词
- [ ] Body 第一段说明 skill 做什么（1-2 句）
- [ ] 有 `## Process` 章节，按步骤编号
- [ ] 有 `## Completion criteria` 章节，每项是 binary checkbox
- [ ] 有 `## 在 Hermes 中的编排` 章节（声明与 loop pattern 的关系）
- [ ] 如适用，有 `## Why` 章节解释设计选择
- [ ] 如适用，有失败模式声明
- [ ] 不超过 200 行（超过则拆分或用 progressive disclosure）

## 四、与 Hermes 的集成

| Hermes 概念 | 词汇表对应 |
|------------|-----------|
| LOOP_PATTERNS sub_agents | Skill 的"被调用"声明 |
| Orchestrator.fan_out | Skill 的"调用"并行声明 |
| audit_loop 检查项 #2 | Completion criteria 对应 |
| skill-up eval.yaml | 验证 SKILL.md 内容完整性 |

## 五、反模式

1. **大而全 skill**：一个 skill 试图覆盖所有场景 → 拆分
2. **无触发词**：frontmatter 无 triggers → 调度器无法触发
3. **无完成标准**：没有 Completion criteria → 无法判断是否完成
4. **Happy path only**：不声明失败模式 → agent 遇到边界时崩溃
5. **隐式依赖**：不声明调用的其他 skill → 组合时断裂
