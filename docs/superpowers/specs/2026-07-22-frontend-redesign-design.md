# Hermes KB M2 前端重设计 设计 Spec

> 日期：2026-07-22 · 状态：已批准 · 作者：产品+设计
> 上游：05-产品定位、06-业务场景与核心能力
> 下游：实现计划 2026-07-22-frontend-redesign.md

---

## 1. 背景与目标

### 1.1 背景
M1 已交付引用式问答后端闭环，但前端为 MVP 单页 Tab 形态，8 个组件堆叠，缺乏专业感与垂直辨识度。M2 需推翻现有前端，基于 05/06 战略基线重新设计前端形态。

### 1.2 目标
产出完整设计交付物：**1 文档 + 13 低保真 + 14 高保真 = 28 文件**，推翻现有 8 个前端组件，建立高级酒类杂志感视觉语言。

### 1.3 范围
- 纯静态 HTML/CSS/JS 设计稿（mockup 高保真 + prototype 低保真）
- 不含后端实现，不含构建工具链
- 教学投影模式、多租户预留**已移除**

---

## 2. 视觉系统（设计 Token）

### 2.1 色彩

**品牌主色（深酒红）**
| Token | 值 | 用途 |
|---|---|---|
| `--brand-50` | #FBF1F4 | 极浅底 |
| `--brand-100` | #F5DDE4 | 气泡背景 |
| `--brand-700` | #8B1A36 | 主色·按钮/强调 |
| `--brand-900` | #4A0E1C | 渐变终点 |

**强调色（暗金）**
| Token | 值 | 用途 |
|---|---|---|
| `--gold-100` | #FAF3DC | 引用卡片背景 |
| `--gold-500` | #C9A227 | 引用边框/数字/装饰 |
| `--gold-700` | #8C7016 | 深金描边 |

**暖灰墨色（文本/底色）**
| Token | 值 | 用途 |
|---|---|---|
| `--ink-50` | #F7F5F3 | 页面底 |
| `--ink-100` | #EDE9E4 | 表头/分隔 |
| `--ink-900` | #1F1C18 | 正文主色 |

**语义色**
`--highlight:#FFF3B8`（chunk 高亮）/ `--success` / `--warning` / `--danger` / `--info`

### 2.2 字体
- 标题：`--font-serif: "Noto Serif SC", serif`（杂志感权威）
- 正文：`--font-sans: Inter, -apple-system, sans-serif`
- 等宽：`--font-mono: JetBrains Mono`（时间戳/IP）

### 2.3 字号
`--fs-xs:.75rem` / `--fs-sm:.875rem` / `--fs-base:1rem` / `--fs-lg:1.125rem` / `--fs-xl:1.375rem` / `--fs-2xl:1.75rem` / `--fs-3xl:2.5rem` / `--fs-hero:3.5rem`

### 2.4 间距
`--sp-1:.25rem` ~ `--sp-16:4rem`（1/2/3/4/6/8/12/16）

### 2.5 圆角
`--r-sm:4px` / `--r-md:8px` / `--r-lg:14px` / `--r-full:9999px`

### 2.6 阴影
`--shadow-sm` / `--shadow-md` / `--shadow-lg`

### 2.7 动效
- `--duration-fast:150ms` / `--duration-base:250ms`
- `--duration-highlight:2000ms`（chunk 高亮淡出，硬约束）
- `--ease-out: cubic-bezier(0.16,1,0.3,1)`

---

## 3. 页面清单与交付物

### 3.1 交付物总数：28 文件

| 类别 | 数量 | 路径 |
|---|---|---|
| 设计文档 | 1 | design/README.md |
| 高保真设计稿 | 15 | design/mockup/（9 页 + 3 modal + 3 共享资产） |
| 低保真原型 | 13 | design/prototype/（9 页 + 3 modal + 1 共享 CSS） |

> 高保真 15 = _tokens.css + _components.css + _nav.js + 9 页面 HTML + 3 modal HTML；交付口径"14 高保真"指 9 页 + 3 modal + README 视觉稿，3 共享资产为支撑文件。

### 3.2 页面清单

| 页面 | data-page | 业务场景 | 核心能力 |
|---|---|---|---|
| index.html | home | F 冷启动 | 价值认知 |
| ask.html | ask | A 问答 | CAP1/2/3 |
| doc-detail.html | docs | B 文档 | CAP2 chunk 高亮 |
| docs.html | docs | B 文档 | CAP4/5 |
| tags.html | tags | C 组织 | CAP5 |
| history.html | history | D 回顾 | CAP6 FTS5 |
| dashboard.html | dashboard | D 回顾 | CAP7 飞轮 |
| audit.html | audit | E 治理 | CAP8 审计 |
| export.html | export | E 治理 | CAP8 导出 |
| _modal-age-gate | modal-age-gate | F 冷启动 | 合规 |
| _modal-login | modal-login | F 冷启动 | 合规 |
| _modal-import | modal-import | B 文档 | CAP4 导入 |

---

## 4. 交互细节

### 4.1 引用卡片（CAP1 硬约束）
- 背景 `--gold-100` + 左边框 3px `--gold-500`
- **不折叠**，固定展示所有引用
- 编号用衬线 `--brand-700`
- 每条引用可点击跳转 `doc-detail.html?chunk=N`

### 4.2 chunk 高亮跳转（CAP2 硬约束）
- `_nav.js` 解析 `?chunk=N`，DOMContentLoaded 后滚动到 `#chunk-N`
- 滚动定位 < 500ms（`scroll-behavior: smooth`）
- 目标 chunk 添加 `.chunk-highlight` 类，2000ms 淡金动画（`@keyframes highlightFade`）

### 4.3 SSE 流式问答（CAP3）
- 事件类型 meta/delta/done/error
- meta 事件先下发引用，正文逐字 opacity 150ms
- 重新提问 abort 上一次（AbortController）
- 空状态：3 个示例问题按钮

### 4.4 文档导入（CAP4）
- 三 tab：粘贴文本 / 上传文件 / 批量上传
- 拖拽区虚线边框
- 批量上传：整体进度条 + 当前文件名 + 失败列表

### 4.5 知识组织（CAP5）
- 分类：单选下拉，7 预设
- 标签：多选 chip，8 色预设 swatch
- 标签 CRUD + 色彩 + 关联文档数

### 4.6 历史全文搜索（CAP6）
- FTS5 搜索 + 时间范围
- 关键词 `<mark>` 高亮（`--highlight` 背景）
- 时间线布局，低置信黄色标记

### 4.7 飞轮健康度（CAP7）
- 4 指标卡：文档/分片/问答/置信度
- 环形进度图（conic-gradient）+ 4 维度
- 7 日 token 柱状图

### 4.8 审计日志（CAP8）
- 筛选：操作类型/时间/用户
- 操作类型色彩 chip：导入蓝/删除红/问答金/登录灰/标签绿
- 分页 + CSV 导出

### 4.9 数据导出（CAP8）
- 全量 JSON / 单文档 MD·JSON / BibTeX 灰显预留

### 4.10 冷启动引导链（L0-L4）
L0 年龄门 → L1 品牌首页 → L2 空问答引导 → L3 首次问答后引导 → L4 空文档库引导

### 4.11 共享导航
- `_nav.js` 注入 7 导航链接 + 导入/导出/登录按钮
- active 由 `body data-page` 控制
- 含 chunk 高亮逻辑

---

## 5. 实现路径

### 5.1 低保真 vs 高保真边界

| 维度 | 低保真 | 高保真 |
|---|---|---|
| 色彩 | 纯灰阶 | 完整 token |
| 字体 | 系统无衬线 | 衬线+无衬线 |
| 内容 | 占位文字 | 真实酒类内容 |
| 交互 | 仅链接 | 完整 JS 演示 |
| 目的 | 信息架构评审 | 视觉评审 |

### 5.2 技术约束
- 纯静态 HTML/CSS/JS，无构建工具
- 高保真引入 Google Fonts（Noto Serif SC + Inter）
- 共享资产：_tokens.css / _components.css / _nav.js
- 低保真：_shared.css，无 Google Fonts

### 5.3 文件结构
```
design/
├── README.md
├── mockup/          # 高保真
│   ├── _tokens.css
│   ├── _components.css
│   ├── _nav.js
│   ├── index.html ... export.html  (9 页)
│   └── _modal-*.html               (3 modal)
└── prototype/       # 低保真
    ├── _shared.css
    ├── index.html ... export.html  (9 页)
    └── _modal-*.html               (3 modal)
```

### 5.4 风险与缓解

| 风险 | 缓解 |
|---|---|
| 文件数多易遗漏 | 28 文件清单逐项核对 |
| 高低保真风格混淆 | grep 检查低保真无彩色 |
| 引用跳转断裂 | chunk id 与 ?chunk=N 对齐 |
| 设计稿无后端 | 静态原型，文案真实即可 |

---

## 6. 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| D15 | 高级酒类杂志感视觉 | P3 垂直即专业 |
| D16 | 引用卡片 gold-100 + gold-500 左边框 | P1 引用即信任 |
| D17 | chunk 高亮 2000ms 淡金 + smooth | 溯源可感知 |
| D18 | ~~教学投影~~ | 撤销，场景窄 |
| D19 | ~~多租户预留~~ | 撤销，降复杂度 |
| D20 | 冷启动种子六大基酒 | P5 冷启动 |
| D21 | 文档详情双栏 | 深度阅读 + 跳转 |
| D22 | 标签 8 色 swatch | 色彩组织 |
| D23 | 历史 FTS5 + mark 高亮 | 检索体验 |
| D24 | BibTeX 灰显预留 | 远期不实现 |

---

## 7. 验收标准

- [x] 28 文件齐全（1 README + 15 mockup + 13 prototype，含 3 共享资产）
- [x] 高保真引入完整 token 系统，衬线标题 + 酒红 + 暗金
- [x] 低保真严格灰阶，grep 无彩色
- [x] 引用卡片 gold-100 + gold-500 左边框，不折叠
- [x] chunk 高亮 2000ms 动画 + smooth scroll
- [x] 共享导航 _nav.js 注入 + data-page active
- [x] 冷启动 L0-L4 引导链覆盖
- [x] 9 页面单一职责，3 modal 独立可预览
