---
name: banned-words-check
description: >
  多平台违禁词预检（发布检查单的官方词库层）。Use when asked to 查违禁词/合规预检/
  发布前检查/文案体检: run the compliance pre-check API with a platform pack
  (xiaohongshu / douyin / wechat_official) on top of the base red-line rules, and
  explain every BLOCK/WARN hit with a concrete rewrite suggestion. Triggers:
  "违禁词", "合规检查", "发布前检查", "文案体检", "banned words".
---

# 多平台违禁词预检

发布前最后一道文字合规门：基础红线规则（广告法/未成年人/医疗/酒驾/绝对化）
+ 平台词包（按发布平台叠加）。

## 词包说明

- 词包数据位于 `src/hermes/content_team/data/word_packs/{platform}.json`，
  当前为 **starter 起步词库**（基于广告法与平台公开规则整理，非官方全量词库）。
- 接入官方违禁词服务后应整体替换词包内容（JSON 结构不变即可热替换，
  加载器带缓存，替换后需重启进程）。
- severity 语义：`BLOCK` = 红线，默认拦截发布（可人工强制）；
  `WARN` = 警示，建议改写。

## 工作流

1. **预检**：

```bash
curl -X POST "http://localhost:8000/api/compliance/check" \
  -H "Content-Type: application/json" \
  -d '{"title":"全网最低价威士忌","body":"加微信购买，保证不上头","platform":"DOUYIN"}'
```

   返回 `passed / blocking[] / warnings[] / summary`，每条命中含
   `rule_id / rule_name / severity / keyword / source(title|body)`。

2. **逐条改写**：对每个命中给出具体替换建议——
   - 绝对化用语 → 主观表达（"全网最低" → "我买到过最划算的"）
   - 功效承诺 → 个人感受（"保证不上头" → "我喝着不太上头，因人而异"）
   - 站外导流 → 站内合规话术
   - WARN 命中可结合语境保留，但要在审核记录里说明理由

3. **复检确认**：改写后必须重新调用预检，`passed=true` 才进入发布流程。
   BLOCK 未清零时发布会被 dispatcher 拦截（422），除非人工 `force_compliance`。

## 机器原创性预检（配合人工三查）

发布前可先跑机器字面查重（双字组 Jaccard + 最长公共段），缩小人工三查范围：

```bash
curl -X POST "http://localhost:8000/api/originality/check" \
  -H "Content-Type: application/json" \
  -d '{"title":"金汤力入门","body":"正文…","min_similarity":0.2}'
```

返回 `checked`（参考条数）/ `results[]`（`ref_type` content|topic、
`similarity`、`longest_common_run` 最长公共连续段）/ `note`。

使用要点：
- `min_similarity=0.2` 为保守起步值，未用真实参考库校准前，阈值改为 0.3 更稳
- `ref_type=topic` 命中说明与选题库描述（含爆款参考）太过趋同——改写正文而非照搬
- `longest_common_run >= 15 字` 命中即按原创性三查第 1/2 条改写
- 语义查/图片查不在机器层覆盖，仍按下方人工检查单执行

## 注意事项

- 预检是辅助不是豁免：词包之外的违规（如事实性虚假宣传）仍需人工判断。
- 酒类为敏感品类：涉及未成年、医疗功效、酒驾的内容即使词包未命中也应人工否决。
- 不要教用户"绕过检测的替代写法"，只提供合规方向的改写。

## 原创性与声明人工检查单（词包检测不到的盲区）

自动扫描是关键词层，以下盲区必须人工过一遍（发布否决权在人工）：

### 声明台账（客观说法逐条过）
- [ ] 正文里的**数字/数据/排名**（"排名第X""销量第一"之外的一切数字）是否有可核来源？没有 → 删掉或改为主观表述
- [ ] **实测感受**（"亲测""喝了三天"）是否真实发生过？虚构体验 = 红线，AI 起草的"体验"默认不算数
- [ ] **功效未来时**（"能…""会…""保证…"）一律改主观过去时（"我喝下来感觉…"）
- [ ] 涉及**对比品牌**的贬损表述删干净；对比只摆自己的客观参数

### 原创性三查
1. **字面查**：标题与正文（或其片段）有没有舒服地出现在近 30 天爆款里？（用预览爆款的来源链接抽查 2-3 条）
2. **结构查**：结构可学（清单/对比/场景），句子不可抄；连续 15 字以上与他人雷同即改写
3. **图片查**：网图/他人素材是否有使用边界？二次创作的截图打码 + 标注来源

### 商业披露
- 收了钱/拿货/置换的内容，发布时**必须带平台认可的商务声明**（小红书报备/抖音星图），未报备的合作表述按违规处理
- 自购非软广的"好物推荐"如走平台带货链路，按平台披露规则标注

声明台账格式（可写进笔记）：
```
| 声明 | 出处/依据 | 通过? |
|---|---|---|
| "30杯测试" | 自记笔记 | ✅ |
| "低卡配方" | 营养估算 | ⚠️ 改"个人估算" |
```
