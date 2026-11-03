---
title: 复盘方法论与沉淀协议（review playbook）
summary: 从 retrospective 数据到知识条目的半自动流程与启发式规则清单
overview: |
  复盘三步：读数（期间对比/Top5/来源构成）→ 启发式提炼 → 人工确认沉淀。
  distill 端点产出候选 md（不入库），人工确认写入本目录各文件。
  启发式规则全部确定性实现，禁止使用 LLM 自动结论。
type: playbook
---

# 复盘方法论

## 复盘读数（对应 GET /api/analytics/retrospective）

1. 本期 vs 上期：浏览/点赞/总互动涨跌（>±10% 才算信号）
2. Top5 内容：结构去重、来源选题对齐（关联 topic_id）
3. 来源构成：adapter/manual/simulation 占比——simulation 占比高时先修回采再谈优化

## 启发式规则（distill 端点内实现，确定性）

| 信号 | 提炼候选 |
|---|---|
| 本期互动 ↑ >10% 且 Top1 集中于单一结构 | "结构 xxx 本期有效，回填 viral-structures 验证区" |
| 收藏/点赞比 > 1.5 | "实用价值导向成立，标题往清单型倾斜" |
| 互动 ↓ >10% 且 manual 来源占比 >80% | "回填质量优先于新增内容：先补 adapter 采集" |
| 无 simulation 数据且 manual=0 | "数据断流：'复盘无依据'而非'优化无方向'" |
| Top5 中出现新选题词包 | "选题库词包扩展候选（人工确认）" |

## 沉淀协议

1. distill 产出 → `candidate/review-{date}.md`（platform 目录外，防止污染权威源）
2. 人工确认 → 精简为 3-6 条决策性语句 → 写入对应文件
3. 每月底清理 candidates（超期未处理即视为放弃）

## 上轮复盘结论存档（用真实数据后逐期追加）

（空——首期复盘后开始填写）
