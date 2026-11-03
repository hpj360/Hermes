---
name: xhs-hot-notes
description: >
  小红书爆款笔记数据驱动选题。Use when asked to 找选题/选品参考/爆款分析/低粉爆款/
  小红书热门笔记查询: query hot XHS notes via the Hermes trends API (红狐Hub provider,
  fixture fallback), filter by engagement and follower count, review candidates, then
  import the good ones into the topic library for the SOP builder. Triggers:
  "找选题", "爆款笔记", "低粉爆款", "小红书热门", "选题灵感", "hot notes".
---

# 小红书爆款笔记选题

从爆款数据出发做选题：查询 → 人工筛选 → 导入选题库 → SOP 生成草稿。

## 数据源说明

- Hermes 后端 Provider 优先使用红狐Hub API（需环境变量
  `HERMES_HONGHU_BASE_URL` + `HERMES_HONGHU_API_KEY`）。
- 未配置时自动回退 `fixture` 样例数据（**虚构样例，仅用于开发/演示**，
  输出的 `source` 字段会如实标注 `fixture`）。切勿把 fixture 数据当作真实市场数据
  用于运营决策。
- 红狐Hub 接口路径默认占位（`/v1/xhs/hot-notes`），接入前需按其真实 API
  契约核对 `HERMES_HONGHU_NOTES_PATH`。

## 工作流

1. **查询爆款**：

```bash
curl "http://localhost:8000/api/trends/hot-notes?platform=XIAOHONGSHU&keyword=居家调酒&limit=20"
```

   返回 `notes[]`，每条含 `title / likes / collects / comments / shares /
   engagement / author_fans / url / source`。

2. **人工筛选**（半自动原则）：剔除与账号定位（酒类/居家调酒）无关的条目；
   优先看 `collects`（收藏代表实用价值）与 `engagement`；新号用
   `author_fans` 过滤大号干扰。

3. **导入选题库**：

```bash
curl -X POST "http://localhost:8000/api/trends/import" \
  -H "Content-Type: application/json" \
  -d '{"platform":"XIAOHONGSHU","keyword":"居家调酒","limit":20,"min_engagement":500,"max_fans":5000}'
```

   按标题去重（与已有选题比对），返回 `imported / skipped_duplicates / topics[]`。
   `max_fans=5000` 即"低粉爆款"模式（红狐Hub Top1 的核心筛选逻辑）。

4. **生成草稿**：对导入的选题调用 `POST /api/topics/{id}/draft`
   （见 `sop-builder` 流程），进入常规创作 SOP。

## 注意事项

- 爆款是参考，不是模板：学结构（钩子/清单/对比），不抄文案（合规检查会拦）。
- 导入的选题 description 内含互动量与来源链接，便于回溯。
- 重复导入安全：同标题自动跳过。
