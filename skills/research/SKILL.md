---
name: research
description: "Background agent that reads the source - code, docs, issues - to answer a research question. Produces a markdown report with citations. Use when user asks to investigate, research, or understand a codebase topic. 适用于用户提到'研究''调研''理解代码''技术调研'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "research"
  - "研究"
  - "调研"
  - "技术调研"
  - "理解代码"
---

# Research

A background agent that reads the source — code, docs, issues — to answer a research question. Produces a markdown report with citations.

适配自 mattpocock/skills (保留 source-first 研究方法论，适配为 Hermes 探索能力)。

## 在 Hermes 中的角色

补齐 Hermes 在"loop 启动前"的探索阶段能力：
- 在 to-spec 之前，用 research 理解现状
- 在 improve-codebase-architecture 中，用 research 深入模块

## Principle: Source is the truth

- **Read the code**, not just docs (docs lie, code doesn't)
- **Read the issues**, not just code (issues reveal intent)
- **Read the git history** for controversial decisions (the "why" lives in commits)
- **Cite everything** (file:line, issue#N, commit SHA)

## Process

### 1. Clarify the question
Restate the research question in one sentence. Note:
- What we want to know
- What we already know (don't re-research)
- What level of detail is needed (overview vs deep-dive)

### 2. Map sources
List where to look:
- Code: which directories/files are likely relevant
- Docs: `knowledge/`, `docs/`, `README.md`
- Issues: GitHub issues/PRs (use GitHub MCP if available)
- Git: `git log` for relevant paths
- External: official docs for dependencies (last resort, prefer local)

### 3. Read + cite
For each source, capture:
- **Finding**: what it says (paraphrase)
- **Citation**: exact location (file:line, issue#N, commit SHA)
- **Confidence**: high (code) / medium (docs) / low (inferred)

### 4. Synthesize
Write report to `.scratch/research-<topic>.md`:

```markdown
# Research: <question>

## TL;DR
[1-3 sentences answering the question directly.]

## Findings

### Finding 1: <title>
**Citation**: `src/hermes/loop.py:195-251`
**Confidence**: high
<explanation>

### Finding 2: <title>
**Citation**: issue #42, commit a1b2c3d
**Confidence**: medium
<explanation>

## Open questions
[Things the sources don't answer. Mark for follow-up.]

## Sources read
- `src/hermes/loop.py` (lines 1-251)
- `knowledge/architecture.md`
- issue #42, #67
- commit a1b2c3d, e4f5g6h
```

### 5. Verify
Before presenting:
- Does every claim have a citation?
- Is the TL;DR supported by the findings?
- Are open questions clearly separated from answered ones?

## Anti-patterns

- **"I think..."**: Research reports cite sources, not opinions. If you can't cite it, it goes in "Open questions".
- **Doc-only research**: Docs drift from code. Always verify critical claims against source.
- **No git history**: The "why" is often in a commit message from 6 months ago. Use `git log -- <path>`.
- **Uncited external sources**: If you read an external doc, cite the URL + date accessed.

## Completion criteria
- [ ] Research question restated in one sentence
- [ ] Sources mapped (code + docs + issues + git)
- [ ] Every finding has a citation (file:line / issue# / commit SHA)
- [ ] Confidence level marked per finding
- [ ] TL;DR present and supported by findings
- [ ] Open questions clearly separated
- [ ] Sources-read list complete

## Related skills（边界声明）

- **grounded-citations**: 引文验证。本 skill 产研究报告，grounded-citations 验证报告中的每个 claim 是否有可验证来源。**强烈建议**：研究类 loop 中，本 skill 输出后必须过一道 grounded-citations。
- **codebase-design**: 架构词汇。本 skill 描述代码现状时使用 codebase-design 的统一词汇（Module/Depth/Seam/Adapter/Leverage/Locality）。
- **improve-codebase-architecture**: 架构分析。本 skill 提供**现状**（代码如何工作），improve-codebase-architecture 提供**改进机会**（如何让它更好）。
- **brave-search / tavily-search**: 外部 web 搜索。本 skill 优先读本地代码/issue/doc；仅当需要查外部权威文档时调用 search skill。
- **summarize**: URL/PDF/YouTube 摘要。原始资料是外部链接时，先用 summarize 提取正文，本 skill 再做分析。
