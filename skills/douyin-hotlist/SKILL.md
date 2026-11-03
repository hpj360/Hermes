---
name: douyin-hotlist
description: >
  抖音热榜选题雷达。Use when asked to 追热点/看抖音热榜/短视频选题/趋势判断:
  fetch the Douyin hot list via the Hermes trends API (红狐Hub provider, fixture
  fallback), read heat values and rising tags, and judge which topics fit the
  account before importing them into the topic library. Triggers:
  "抖音热榜", "追热点", "热榜", "短视频选题", "hot list".
---

# 抖音热榜选题

热榜驱动短视频选题：抓榜 → 判断生命周期 → 匹配账号定位 → 导入。

## 数据源说明

- Provider 优先红狐Hub API（`HERMES_HONGHU_BASE_URL` + `HERMES_HONGHU_API_KEY`）。
- 未配置时回退 `fixture` 样例（虚构数据，`source` 字段如实标注）。
- 热榜接口路径默认占位（`/v1/douyin/hot-list`），接入前按真实契约核对
  `HERMES_HONGHU_HOTLIST_PATH`。

## 工作流

1. **抓热榜**：

```bash
curl "http://localhost:8000/api/trends/hot-list?platform=DOUYIN&limit=50"
```

   返回 `items[]`：`rank / title / heat / tag / url`。`tag` 常见
   `热`（正在爆发）、`上升`（早期信号，优先）、`荐`（平台推荐位）。

2. **判断生命周期**：`上升` 标签抢先布局；`热` 标签看账号能否做出差异化角度；
   热度已见顶的（连续多日霸榜）不追。

3. **匹配账号定位**：酒类账号只接与"微醺/调酒/餐酒/生活方式"有自然连接点的热点，
   硬蹭会掉粉。热点与账号无连接点时直接放弃，不强行接入。

4. **导入与创作**：把选中的热点作为关键词走
   `POST /api/trends/import`（会拉取相关爆款笔记），再进 SOP 草稿流程。

## 注意事项

- 时效敏感：热榜数据按小时更新，决策当天完成创作发布。
- 合规优先：热点若涉政治/灾难/未成年人，酒类账号一律不蹭。
- `fixture` 数据仅用于开发演示，不可用于运营决策。
