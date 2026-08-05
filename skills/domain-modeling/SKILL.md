---
name: domain-modeling
description: "Maintain a living CONTEXT.md that captures the domain glossary, entities, and rules. Prevents ambiguous terms and stale specs. Use when starting a new feature, during spec creation, or when terms feel ambiguous. 适用于用户提到'领域建模''CONTEXT.md''术语表''领域概念'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "domain modeling"
  - "领域建模"
  - "CONTEXT.md"
  - "术语表"
  - "领域概念"
---

# Domain Modeling

Maintain a living `CONTEXT.md` that captures the domain glossary, entities, and rules. Prevents ambiguous terms and stale specs.

适配自 mattpocock/skills (保留 CONTEXT.md 主动维护方法论，激活 Hermes knowledge 被动沉淀为主动建模)。

## 在 Hermes 中的角色

Hermes 的 `knowledge/` 目录是**被动沉淀**（事后记录）。本 skill 激活**主动建模**：
- 在 to-spec 阶段，先查 CONTEXT.md 是否有相关术语
- 在 to-tickets 阶段，新概念写入 CONTEXT.md
- 在 loop 执行后，新发现的领域规则更新 CONTEXT.md

## The CONTEXT.md file

Lives at project root (`/workspace/CONTEXT.md`). Structure:

```markdown
# Project Context

## Glossary
| Term | Definition | First seen |
|------|-----------|------------|
| Loop | A recurring execution cycle with stop rules | architecture.md |
| Harness | Constraints that bound agent behavior | architecture.md |
| Sub-agent | A spawned agent with a specific role | orchestrator.py |
| GEPA | Generate-Evaluate-Promote-Apply self-evolution cycle | gepa.py |

## Entities
### LoopState
- **Identity**: name (unique)
- **Attributes**: pattern, stage, status, current_round, budget_used_tokens
- **Relationships**: has many LoopRound, has many AgentTask (per round)

### AgentTask
- **Identity**: task_id
- **Attributes**: role, allowed_mcp_tools, denylist, token_limit
- **Relationships**: belongs to LoopRound

## Domain Rules
1. A loop stops when one of 7 stop rules triggers (mutually exclusive).
2. L1→L2 requires audit score ≥70; L2→L3 requires ≥85.
3. Builder writes are restricted by denylist; checker writes are always denied.
4. GEPA only promotes successful variants (conservative policy).

## Decisions (link to ADRs)
- [ADR-0001] Process-internal stdlib-only scheduling
- [ADR-0002] Crash recovery: re-queue QUEUED, abandon RUNNING
- [ADR-0003] DAG upstream failure cascades cancel downstream
```

## Process

### 1. Check CONTEXT.md exists
If not, create it with the skeleton above. If yes, read current glossary + entities + rules.

### 2. Scan for new terms
From the current task (spec / conversation / code changes), identify:
- **New terms**: words used that aren't in the glossary
- **Ambiguous terms**: words used differently than the glossary definition
- **New entities**: data objects not yet modeled
- **New rules**: constraints discovered during implementation

### 3. Propose updates
For each finding, propose a glossary entry / entity / rule addition. Present to user:

```
Glossary additions:
  + "Tracer bullet" — A thin end-to-end slice proving architecture works (to-tickets skill)

Entity updates:
  + EvalResult — Identity: workspace; Attributes: cases, all_passed, summary

Rule additions:
  + "skill-up result.json is the single source of truth for eval pass/fail"
```

### 4. Apply updates
After user confirms, update CONTEXT.md. Note in the "First seen" column where the term was first encountered (file/skill name).

### 5. Check for stale entries
Flag glossary terms / rules that haven't been referenced in >30 days. Don't delete — propose archiving to `CONTEXT.archive.md`.

## Why living > static

A static domain model goes stale. A living one:
- Catches ambiguity before it causes bugs ("did you mean Loop the pattern or loop the cycle?")
- Onboards new contributors faster (single source of truth for terms)
- Links decisions to ADRs (no orphan rules)

## Completion criteria
- [ ] CONTEXT.md exists at project root (or was created)
- [ ] All sections present: Glossary, Entities, Domain Rules, Decisions
- [ ] New terms from current task proposed (with source reference)
- [ ] Stale entries flagged (not deleted)
- [ ] Glossary terms link to first-seen location

## Related skills（边界声明）

- **codebase-design**: 架构词汇表（Module/Depth/Seam/Adapter/Leverage/Locality）。本 skill 关注**业务领域**（glossary/entities/rules），codebase-design 关注**代码架构**（词汇表）。两者互补：domain-modeling 回答"业务概念是什么"，codebase-design 回答"代码组织如何"。
- **to-spec**: 需求 → PRD。本 skill 在 to-spec 写 spec 前**主动查询** CONTEXT.md 复用术语，spec 完成后**反向更新** CONTEXT.md 加入新概念。
- **research**: 源码研究。research 描述代码现状时复用本 skill 的术语（Glossary 链接）。
- **triage**: Issue 分诊。triage 在 Grill 阶段引用 CONTEXT.md 避免术语歧义。
- **self-improving-agent**: 经验记录。domain-modeling 维护**业务知识**（CONTEXT.md），self-improving-agent 记录**操作经验**（`.learnings/`）。**不重叠**：业务概念 vs 操作学习。
