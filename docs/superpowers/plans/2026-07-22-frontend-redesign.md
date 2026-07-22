# 前端重设计实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 05/06 战略基线与设计 Spec，产出 Hermes KB M2 全新前端 28 个设计交付文件（1 README + 13 低保真 + 14 高保真），推翻现有 8 个前端组件。

**Architecture:** 纯静态 HTML/CSS/JS 设计稿，分两层——高保真（design/mockup/，完整 token + 真实内容 + 交互演示）与低保真（design/prototype/，灰阶线框 + 占位文字 + 仅链接）。共享资产 _tokens.css/_components.css/_nav.js 支撑高保真，_shared.css 支撑低保真。

**Tech Stack:** HTML5 + CSS3（CSS 变量 + conic-gradient + keyframes）+ 原生 JS（无框架无构建）。Google Fonts（Noto Serif SC + Inter）。

---

## 文件结构

```
design/
├── README.md                          # Task 1
├── mockup/                            # 高保真
│   ├── _tokens.css                    # Task 2
│   ├── _components.css                # Task 2
│   ├── _nav.js                        # Task 2
│   ├── index.html                     # Task 3
│   ├── ask.html                       # Task 4
│   ├── doc-detail.html                # Task 5
│   ├── docs.html + tags.html          # Task 6
│   ├── history.html + dashboard.html  # Task 7
│   ├── audit.html + export.html       # Task 8
│   └── _modal-*.html (3)              # Task 9
└── prototype/                         # 低保真
    ├── _shared.css                    # Task 10
    └── 9 页 + 3 modal                 # Task 10
```

---

## Task 1: 目录结构 + README

**Files:**
- Create: `design/README.md`

- [x] Step 1: 创建 design/README.md，说明目录结构（mockup 高保真 / prototype 低保真）+ 预览方式 + token 迁移说明
- [x] Step 2: commit + push

## Task 2: 设计 token + 组件 + 共享导航

**Files:**
- Create: `design/mockup/_tokens.css`, `design/mockup/_components.css`, `design/mockup/_nav.js`

- [x] Step 1: _tokens.css — Spec §2 全部 token（色彩 brand/gold/ink + 语义 + 字体 + 字号 + 间距 + 圆角 + 阴影 + 动效 + 布局变量，50+ 变量）
- [x] Step 2: _components.css — Spec §2.7 + §4.11 全部组件（.btn-primary/secondary/ghost/danger + .card + .input/.select/.textarea + .citation-list[gold-100+gold-500 左边框+不折叠+brand-700 编号] + .chunk-highlight[highlightFade 2000ms] + .tag-* + .table + .modal/.modal-overlay + .skeleton + .toast + .empty-state + .low-confidence + .nav）
- [x] Step 3: _nav.js — 共享导航注入（7 链接 + 导入/导出/登录按钮，active 由 body data-page 控制）+ chunk 高亮逻辑（解析 ?chunk=N，DOMContentLoaded 后 scrollIntoView smooth + 添加 .chunk-highlight 类）
- [x] Step 4: commit + push

## Task 3: 品牌首页 index.html

**Files:** Create: `design/mockup/index.html`

- [x] Step 1: Hero 区（酒红渐变 + 酒窖头图 + 衬线大标题"你的私人酒类知识管家" + 双 CTA）
- [x] Step 2: 头条问答区（精选问答 + .citation-list 3 条引用，可点击跳转 doc-detail.html?chunk=3）
- [x] Step 3: 热门文档区（5 张 .card：金酒/威士忌/葡萄酒/中国白酒/朗姆酒）
- [x] Step 4: 分类入口区（7 个圆形 PRESET_CATEGORIES，暗金描边 + hover 放大）
- [x] Step 5: commit + push

## Task 4: 问答页 ask.html

**Files:** Create: `design/mockup/ask.html`

- [x] Step 1: 空状态引导（3 个示例问题按钮，fillExample 填充）
- [x] Step 2: 对话区（用户气泡 brand-100 右对齐 + AI 答案 + .citation-list 3 条引用 + 反馈 👍👎 + .low-confidence）
- [x] Step 3: 底部输入区（textarea + 发送按钮 + 回车发送）
- [x] Step 4: JS sendQuestion() 切换空状态→对话区
- [x] Step 5: commit + push

## Task 5: 文档详情页 doc-detail.html

**Files:** Create: `design/mockup/doc-detail.html`

- [x] Step 1: 双栏布局（左目录 width:--sidebar 300px + 右全文 flex:1）
- [x] Step 2: 左目录（标题 + 元信息 chip + 5 章节链接，active gold-500 左边框 + brand-700）
- [x] Step 3: 右全文 5 个 section#chunk-N（N=1,3,5,7,9），chunk-3 含波本威士忌详细内容
- [x] Step 4: 操作按钮区（基于此文档提问/下载MD/编辑/删除）
- [x] Step 5: scrollspy（IntersectionObserver 更新左目录 active）
- [x] Step 6: commit + push

## Task 6: 文档库 + 标签管理

**Files:** Create: `design/mockup/docs.html`, `design/mockup/tags.html`

- [x] Step 1: docs.html 筛选栏（分类下拉 7 类 + 标签下拉 + 搜索 + 清除 + "共 N 篇"统计）
- [x] Step 2: docs.html 表格（7 列 + 5 行真实文档，标签 chip 配色，标题跳转 doc-detail）
- [x] Step 3: docs.html 空状态 + 导入按钮→_modal-import.html
- [x] Step 4: tags.html 创建区（输入 + 8 色 swatch + 创建按钮）
- [x] Step 5: tags.html 标签列表（5 个真实标签 + 关联数 + 编辑/删除 confirm）
- [x] Step 6: commit + push

## Task 7: 历史回溯 + 仪表盘

**Files:** Create: `design/mockup/history.html`, `design/mockup/dashboard.html`

- [x] Step 1: history.html 搜索栏（关键词 + 时间范围 + 搜索按钮）
- [x] Step 2: history.html 时间线（5-6 条记录 + 时间戳 + 问题 + 答案摘要 + 引用 chip + .low-confidence + `<mark>` 高亮）
- [x] Step 3: history.html JS doSearch() 过滤 + 高亮 + 空状态
- [x] Step 4: dashboard.html 4 指标卡（文档47/分片312/问答42/置信度0.87）
- [x] Step 5: dashboard.html 飞轮健康度（conic-gradient 环形图 74/100 + 4 维度进度条）
- [x] Step 6: dashboard.html token 柱状图（7 日 + 汇总 + 模型分布 chip）
- [x] Step 7: commit + push

## Task 8: 审计日志 + 数据导出

**Files:** Create: `design/mockup/audit.html`, `design/mockup/export.html`

- [x] Step 1: audit.html 筛选栏（操作类型 + 时间 + 用户 + 重置/筛选）
- [x] Step 2: audit.html 表格（6 列 + 8-9 行 + 操作类型 chip 配色）
- [x] Step 3: audit.html 分页 + CSV 导出按钮
- [x] Step 4: export.html 3 卡片（全量JSON + 单文档MD/JSON + BibTeX 灰显 opacity:0.5）
- [x] Step 5: export.html 导出历史区（3 条记录）
- [x] Step 6: commit + push

## Task 9: 三个 modal

**Files:** Create: `design/mockup/_modal-age-gate.html`, `_modal-login.html`, `_modal-import.html`

- [x] Step 1: age-gate（深酒红渐变 + 暗金描边 + 衬线标题 + 2 按钮 + 合规声明）
- [x] Step 2: login（白底 + 衬线标题 + 密码输入 + 记住我 + 全宽按钮 + 错误提示）
- [x] Step 3: import（600px + 三 tab JS 切换：粘贴文本/上传文件/批量上传 + 拖拽区 + 文件队列 + 进度条 + 失败列表）
- [x] Step 4: 每个含演示触发按钮
- [x] Step 5: commit + push

## Task 10: 低保真原型 13 文件

**Files:** Create: `design/prototype/`（_shared.css + 9 页 + 3 modal）

- [x] Step 1: _shared.css（5 灰阶变量 + 系统无衬线 + .box/.box-img/.box-text/.label/.nav/.btn-wire/.annot + `*{color:--w-text}` 强制灰阶）
- [x] Step 2: 9 页面低保真（统一 nav + .box 占位 + .annot 标注 + `<a>` 互联，无 JS 无 button）
- [x] Step 3: 3 modal 低保真（遮罩 rgba(0,0,0,0.4) + 占位卡片 + [显示 modal] 文字）
- [x] Step 4: grep 验证无彩色/无衬线/无 script/无 button/无 onclick（零匹配）
- [x] Step 5: commit + push

---

## Self-Review

**1. Spec 覆盖：** Spec §1-7 全部由 Task 1-10 覆盖。视觉系统→Task 2；9 页面→Task 3-8；3 modal→Task 9；低保真→Task 10；README→Task 1。✅

**2. Placeholder 扫描：** 无 TBD/TODO，每步含具体文件与内容要求。✅

**3. 类型一致性：** .citation-list / .chunk-highlight / .low-confidence / body data-page 等命名跨 Task 一致。✅

**4. 决策对齐：** D15-D24 全部落点：D15→token，D16→citation-list，D17→chunk-highlight，D18/D19 撤销，D20→种子，D21→doc-detail 双栏，D22→tags swatch，D23→history mark，D24→BibTeX 灰显。✅
