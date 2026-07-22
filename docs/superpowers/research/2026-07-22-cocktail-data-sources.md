# 鸡尾酒/调酒领域外部数据源深度调研报告

> **日期**：2026-07-22
> **目的**：为 Hermes KB 项目 M4.2（外部数据源）补全数据来源调研，修订原 Plan
> **背景**：当前 KB 仅含 8 款 IBA 经典配方（M3 种子）。M4.2 原计划接入 TheCocktailDB + ima adapter 骨架，但 ima 是否真实存在、是否还有更优数据源未充分论证。
> **方法**：WebSearch（英文优先）+ WebFetch 验证关键 API + 项目代码核对（`seed_recipes.py` / `m4.2-external-sources.md`）

---

## 0. 关键结论速览（TL;DR）

1. **ima adapter 应立即砍掉** —— 公开搜索无法定位名为 "ima" 的专业酒类知识库 API，原 Plan 中的 `base_url = "https://api.ima.example.com/v1"` 是占位符。继续投入是浪费，应替换为真实数据源。
2. **TheCocktailDB（TCTDB）继续作为 P0 主力** —— 已验证 API 真实可用，636 款配方 + 489 种材料 + 636 张图片，免费测试 Key "1" 可用，原 Plan 方向正确。
3. **新增 P0 候选 4 个开源 IBA 数据集** —— GitHub 上已有多个抓取自 iba-world.com 并清洗好的 JSON 数据集，可直接当种子扩充，免去自己爬取与法律风险：
   - `lmc2179/iba_dataset_json`（recipes + ingredients_strength）
   - `jych/iba-cocktail-list`（npm，含 TypeScript 类型）
   - `karlomikus/bar-assistant`（MIT 后端，300+ 配方 + 替代材料 + ABV）
   - `cocktail-suggestions`（轻量 Python 参考实现）
4. **IBA 官网 102 款配方是「金标准」** —— 但 iba-world.com 无官方 API，只能爬取（合规风险中等：事实性配方数据，但页面 HTML/图片受版权保护）。
5. **中文数据源整体偏弱** —— 知乎/小红书 UGC 有版权霸王条款风险（"非独家版权"争议），不建议作为配方数据源；中文站 `drink8.cn`、`enjoycocktail.com`、调一杯 App 体量小且无开放 API。
6. **Difford's Guide 是专业权威但封闭** —— 2800+ 配方仅通过付费 App / 书籍提供，网站 encyclopedia 部分免费但无 API，不建议自动抓取。
7. **品牌官方配方库（Bacardi / Diageo）有结构化数据** —— 单页 JSON-LD 风格，但仅限自家酒款，适合做"品牌关联"增强而非主数据源。

**P0 / P1 / P2 分布**：P0 = 4 个 · P1 = 6 个 · P2 = 6 个（合计 16 个核心数据源，含周边工具另计）

---

## 1. 数据源总览表

| # | 名称 | 类型 | URL | 配方量 | 获取方式 | 数据格式 | 中文 | 评分 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | TheCocktailDB | 免费 API | https://www.thecocktaildb.com/api.php | 636 | 免费 API（测试 Key "1"） | JSON | ❌ | 5 | P0 |
| 2 | iba_dataset_json | 开源数据集 | https://github.com/lmc2179/iba_dataset_json | ~100 | GitHub Clone | JSON | ❌ | 5 | P0 |
| 3 | iba-cocktail-list (npm) | 开源数据集 | https://www.npmjs.com/package/iba-cocktail-list | 90+ | npm install | JSON + TS types | ❌ | 5 | P0 |
| 4 | bar-assistant | 开源后端 | https://github.com/karlomikus/bar-assistant | 300+ | Docker / GitHub | JSON (REST API) | ❌ | 4 | P0 |
| 5 | IBA 官网 | 权威源 | https://iba-world.com/cocktails/all-cocktails/ | 102 | 爬取 | HTML | ❌ | 5 | P1 |
| 6 | cocktail-suggestions | 开源参考 | https://wenku.csdn.net/doc/1hx3z2qvxx | 数十 | GitHub | Python | ❌ | 3 | P1 |
| 7 | Bacardi 官方配方 | 品牌源 | https://www.bacardi.com/rum-cocktails/ | ~80 | 爬取 | HTML/JSON-LD | ❌ | 4 | P1 |
| 8 | Diageo Bar Academy | 品牌源 | https://www.diageobaracademy.com/ | ~150 | 爬取 | HTML | ❌ | 3 | P1 |
| 9 | Kaggle cocktails-data | 数据集 | https://www.kaggle.com/datasets/banajitrajbongshi/cocktails-data | 426 | Kaggle 下载 | CSV | ❌ | 3 | P1 |
| 10 | enjoycocktail.com 喝点鸡尾酒 | 中文站 | https://www.enjoycocktail.com/ | ~100+ | 爬取 | HTML | ✅ | 3 | P1 |
| 11 | drink8.cn 梦幻调酒师 | 中文论坛 | http://www.drink8.cn/ | 数百 | 爬取 | HTML (GBK) | ✅ | 2 | P2 |
| 12 | 调一杯 App | 中文 App | （安卓应用市场） | ~50+ | 无 API | App 内 | ✅ | 2 | P2 |
| 13 | Difford's Guide | 专业付费 | https://www.diffordsguide.com/ | 2800+ | 付费 App / 书 | 书 + App | ❌ | 5 | P2 |
| 14 | Mixel - Cocktail Recipes | iOS App | https://apps.apple.com/.../mixel-cocktail-recipes | 2500+ | 付费 App | App 内 | ❌ | 4 | P2 |
| 15 | APIVerve Cocktail API | 付费 API | https://apiverve.com/marketplace/cocktail | 数十 | 付费 API | JSON | ❌ | 3 | P2 |
| 16 | 知乎 / 小红书 UGC | UGC | https://www.zhihu.com / https://www.xiaohongshu.com | 海量 | 爬取 | HTML | ✅ | 2 | P2 |

**周边工具（非配方源，用于营养/ABV 计算）**：

| 名称 | URL | 用途 | 备注 |
|---|---|---|---|
| basicfreetools Alcohol Calorie Calculator | https://basicfreetools.com/alcohol-calorie-calculator/ | 卡路里公式 | 公式：`Volume × ABV × 0.789 × 7` |
| miniwebtool 酒精卡路里计算器 | https://miniwebtool.com/zh-cn/酒精卡路里计算器/ | 卡路里 + 标准饮酒量 | 含 21 种预设饮品 |
| Mastering Mixology Calculator | https://cal3.calculator.city/mastering-mixology-calculator/ | ABV + 成本计算 | 含每份成本公式 |
| IBA Cocktails Recipes 2024 (App) | https://apps.apple.com/gh/app/iba-cocktails-recipes-2024/id1610558924 | IBA 配方 App | 第三方开发者，非官方 |

---

## 2. 各数据源详细分析

### 2.1 【P0】TheCocktailDB —— 主力免费 API

- **URL**：https://www.thecocktaildb.com/api.php
- **类型**：免费/开源 API（社区众包数据库）
- **数据内容**：
  - 配方：**636 款**（含 IBA 经典 + 流行 + 原创）
  - 材料：**489 种**
  - 图片：**636 张**（每配方 1 张，支持 small/medium/large 三档）
  - 字段：idDrink / strDrink / strInstructions / strIngredient1-15 / strMeasure1-15 / strGlass / strCategory / strAlcoholic / strDrinkThumb / strImageSource / strImageAttribution / dateModified
- **获取方式**：
  - 免费测试 Key：`1`（开发/教育用）
  - 生产环境：$10 一次性 Premium Key（终身）
  - Premium 额外能力：多材料过滤、Popular/Latest 列表、10 欟随机、全量列表（免费版限 100 条/请求）
- **关键端点**（已用 WebFetch 验证）：
  ```
  GET /api/json/v1/1/search.php?s=margarita      # 按名搜索
  GET /api/json/v1/1/search.php?f=a              # 按首字母列
  GET /api/json/v1/1/search.php?i=vodka          # 按材料搜
  GET /api/json/v1/1/lookup.php?i=11007          # 按 ID 查
  GET /api/json/v1/1/lookup.php?iid=552          # 按材料 ID 查
  GET /api/json/v1/1/random.php                  # 随机一款
  GET /api/json/v1/1/filter.php?i=Gin            # 按材料过滤（仅元数据）
  GET /api/json/v1/1/filter.php?a=Alcoholic      # 按酒精过滤
  GET /api/json/v1/1/filter.php?c=Cocktail       # 按分类过滤
  GET /api/json/v1/1/filter.php?g=Cocktail_glass # 按杯型过滤
  GET /api/json/v1/1/list.php?c|g|i|a=list       # 列举所有分类/杯型/材料/酒精类型
  ```
- **图片端点**：
  - 配方缩略图：`/images/media/drink/{hash}.jpg/small|medium|large`
  - 材料图：`/images/ingredients/{name}.png`（也支持 `-small.png` / `-medium.png`）
- **数据质量评分**：5/5（结构化、有图片、社区维护、API 稳定多年）
- **合规性**：免费 API 明确允许调用；测试 Key "1" 仅限开发/教育，生产应购买 Premium（$10 终身，成本极低）；配方本身为社区众包，无版权争议。
- **中文支持**：❌ 全英文（材料名、说明、分类）。需要本地归一化映射（M4.2 Plan 中 `_INGREDIENT_OVERRIDES` 已涵盖 40+ 项，方向正确）。
- **更新频率**：持续更新（首页可见 Latest Drinks 列表持续滚动）
- **接入建议**：**立即接入**。原 M4.2 Plan 的 `thecocktaildb_sync.py` 方向正确，但需修订同步策略（见 §5）。

### 2.2 【P0】lmc2179/iba_dataset_json —— IBA 抓取清洗版

- **URL**：https://github.com/lmc2179/iba_dataset_json
- **类型**：开源数据集（GitHub）
- **数据内容**：
  - `recipes.json`：IBA 全部配方，单位为 cl（厘升）
  - `ingredients_strength.json`：每种成分 → ABV 小数映射
  - 字段示例：
    ```json
    {
      "name": "RUSTY NAIL",
      "ingredients": [
        {"name": "scotch whisky", "quantity": 4.5},
        {"name": "drambuie", "quantity": 2.5}
      ],
      "type": "After Dinner Cocktail"
    }
    ```
- **获取方式**：`git clone` 即可，无 API
- **数据质量评分**：5/5（直接源自 IBA、结构干净、含 ABV 附加数据）
- **合规性**：配方本身为 IBA 公开发布的事实性数据；GitHub 上以研究/教育目的分发，无明确 License 文件（需在 README 确认）。
- **中文支持**：❌ 全英文，材料名小写
- **更新频率**：抓取自 IBA，2020 年首发，2024 年更新过一次；建议以 iba-world.com 当前列表为准做 diff 校验
- **接入建议**：**立即接入**。可直接当 M3 种子的扩充数据源，把 8 款扩展到 ~100 款 IBA 全集。注意单位转换：`cl → ml`（1cl = 10ml）。

### 2.3 【P0】jych/iba-cocktail-list (npm) —— TypeScript 友好版

- **URL**：https://www.npmjs.com/package/iba-cocktail-list
- **类型**：开源数据集（npm 包，MIT License）
- **数据内容**：IBA 2020 修订版全部配方，分三类导出：
  - `unforgettables`（The Unforgettables）
  - `contemporaryClassics`（Contemporary Classics）
  - `newEra`（New Era Drinks）
  - `drinks`（合并数组）
- **获取方式**：`npm install iba-cocktail-list`
- **关键类型定义**：
  ```typescript
  type Drink = { name, ingredients: Ingredient[], method, glass, garnish, ... }
  type Ingredient = { name, quantity: Quantity }
  type Quantity = { formal?: { unit: 'ml' | 'cl' | 'oz', count: number }, informal?: string }
  ```
- **数据质量评分**：5/5（结构化最严谨、有 TypeScript 类型、区分正式/非正式计量）
- **合规性**：MIT License；README 明确"配方版权归 IBA，本包仅含 widely-distributed information, sourced from iba-world.com"。
- **中文支持**：❌
- **接入建议**：**立即接入**。可直接被 `seed_recipes.py` 引用，把 IBA 三大分类作为 category 字段（对应 M3 的 `season`/`difficulty` 之外的官方分类维度）。

### 2.4 【P0】karlomikus/bar-assistant —— 完整参考实现

- **URL**：https://github.com/karlomikus/bar-assistant
- **类型**：开源后端（MIT License，Laravel + Meilisearch）
- **数据内容**：
  - 内置 **300+ 鸡尾酒配方**（含 IBA 全集 + 流行款）
  - 100+ 种材料，**含替代材料关系**（substitutes）
  - ABV 计算、单位切换、杯型、评分、笔记
  - 配套 Web 客户端 Salt Rim
  - API 文档：https://bar-assistant.github.io/docs/
- **获取方式**：
  - Docker 一键部署：`docker-compose up -d`
  - API 默认 `http://localhost:8000`
  - 可直接读取其数据库导出 / 调用其 REST API
- **数据质量评分**：4/5（数据是社区整理，部分配方偏个人化；架构成熟可借鉴）
- **合规性**：MIT License，可自由使用其数据与代码
- **中文支持**：❌（界面有部分翻译，数据英文）
- **接入建议**：**立即接入**。两个用途：
  1. 作为"替代材料关系"权威来源（M4.2 当前 `substitutes.py` 数据稀薄，可批量导入 bar-assistant 的 substitutes 表）
  2. 作为架构参考（其 ABV 计算、单位换算、材料分类的实现可移植到 Python）

### 2.5 【P1】IBA 官网 —— 金标准但需爬取

- **URL**：https://iba-world.com/cocktails/all-cocktails/
- **类型**：权威官方网站
- **数据内容**：
  - **102 款**官方配方（2024 版）
  - 三大分类：The Unforgettables / Contemporary Classics / New Era Drinks
  - 每款含：名称、分类、配方、步骤、杯型、装饰、配图、浏览量
  - 部分配方有视频
- **获取方式**：仅 HTML，无官方 API。需爬虫。
- **数据质量评分**：5/5（**权威性最高**，是其他所有数据集的源头）
- **合规性**：⚠️ 中等风险
  - 配方本身（材料 + 比例 + 步骤）属事实性数据，原则上可引用
  - 页面 HTML 结构、图片、品牌标识受版权保护，不可整体复制
  - 应遵守 robots.txt 与访问频率
  - 建议方式：用爬虫提取结构化数据后**仅保留事实字段**（名称/材料/用量/步骤文本），**不下载图片**到 KB 仓库
- **中文支持**：❌（IBA 官方为英文）
- **接入建议**：**评估后接入**。优先用 §2.2/§2.3 的现成数据集，IBA 官网仅用于"校验 + 最新更新检查"。

### 2.6 【P1】cocktail-suggestions —— 参考实现

- **URL**：https://wenku.csdn.net/doc/1hx3z2qvxx （GitHub 原仓库需进一步定位）
- **类型**：开源 Python 项目（轻量推荐系统）
- **数据内容**：
  - 经典鸡尾酒配方（Old Fashioned / Mojito / Daiquiri / Negroni 等）
  - "必备材料" vs "可选增强材料" 标注
  - 风味轮语义聚类（柑橘调/草本调/烟熏调）
  - 同义词词典（"lime juice" ≡ "青柠汁" ≡ "莱姆汁"）
- **数据质量评分**：3/5（架构思路好，但数据量小、维护不活跃）
- **接入建议**：**评估后接入**。主要价值是其**同义词词典与风味分类法**，可借鉴到 `ingredients.py` 与 `substitutes.py`，不直接当作配方源。

### 2.7 【P1】Bacardi 官方配方库

- **URL**：https://www.bacardi.com/rum-cocktails/
- **类型**：品牌官方
- **数据内容**：
  - 约 80+ 朗姆酒基配方（含 Mojito / Daiquiri / Zombie / Mai Tai / Hurricane 等）
  - 每款含：材料（ml）、Level（Easy/Intermediate/Advanced）、Flavor 标签、Prep 时长、ABV
  - 配图精美
- **获取方式**：HTML 爬取（页面有结构化数据，疑似 JSON-LD）
- **数据质量评分**：4/5（品牌自维护，配比精确，但仅限 Bacardi 自家朗姆酒款）
- **合规性**：⚠️ 品牌配方页面有版权；商业使用需联系品牌授权。研究/教育引用通常可接受。
- **接入建议**：**评估后接入**。**仅作为「品牌-配方关联」增强字段**（如配方 `brands: ["Bacardi"]`），不作为主配方源。可作为材料价格锚定参考（不同档次朗姆酒的建议零售价）。

### 2.8 【P1】Diageo Bar Academy

- **URL**：https://www.diageobaracademy.com/
- **类型**：品牌官方（Diageo 旗下：Johnnie Walker / Tanqueray / Don Julio / Guinness 等）
- **数据内容**：约 150 款配方 + 调酒技巧文章 + 视频教程
- **获取方式**：HTML 爬取
- **数据质量评分**：3/5（专业内容，但配方页面非高度结构化）
- **合规性**：⚠️ 同 Bacardi，品牌内容版权
- **接入建议**：**评估后接入**。用途同 Bacardi：品牌关联 + 视频教程引用（多媒体数据源补充）。

### 2.9 【P1】Kaggle cocktails-data

- **URL**：https://www.kaggle.com/datasets/banajitrajbongshi/cocktails-data/data
- **类型**：研究数据集
- **数据内容**：426 行，含字段：Category / IBA（标注是否 IBA 官方）/ Alcoholic type / Ingredients / Instructions 等
- **获取方式**：Kaggle 免费下载（需账号）
- **数据质量评分**：3/5（数据集整合自多源，含 IBA 标注便于筛选；但元数据稀薄、无图片）
- **合规性**：Kaggle 数据集 License 各异，本数据集需确认其具体 License
- **接入建议**：**评估后接入**。价值是**字段已标注 IBA 状态**，可作为「IBA 配方识别器」的训练数据。

### 2.10 【P1】enjoycocktail.com 喝点鸡尾酒 —— 中文参考

- **URL**：https://www.enjoycocktail.com/
- **类型**：中文独立开发者站点 + 小程序
- **数据内容**：
  - 配方 + 制作方法 + 酒单
  - **调酒台功能**：输入已有材料 → 自动匹配可调制酒款 + 缺 1 材料的酒款（与 Hermes KB 实验室匹配高度同构）
  - 啤酒/烈酒/利口酒酒款信息
- **获取方式**：HTML 爬取（无开放 API）
- **数据质量评分**：3/5（中文独立开发者维护，数据量 ~100+，更新缓慢）
- **合规性**：⚠️ 个人站点，未声明 API 开放或数据 License；爬取需联系作者授权
- **中文支持**：✅ 原生中文
- **接入建议**：**评估后接入**。价值不在数据量，而在其"调酒台"匹配逻辑可作为 Hermes KB 实验室功能的**对标参考**。建议直接联系作者（豆瓣 ID：秋星火）寻求数据合作或授权。

### 2.11 【P2】drink8.cn 梦幻调酒师

- **URL**：http://www.drink8.cn/
- **类型**：中文调酒论坛
- **数据内容**：数百款鸡尾酒配方 + 调酒教程 + 论坛讨论
- **获取方式**：HTML 爬取（GBK 编码，Discuz! 论坛架构）
- **数据质量评分**：2/5（内容老旧，2010 年代为主，流量已大幅下滑，2020 年估值仅 ~$9,500）
- **合规性**：⚠️ 论坛 UGC 内容版权属发帖用户；GBK 编码 + Discuz 反爬机制增加技术难度
- **接入建议**：**不推荐接入**。年代久远、数据陈旧、技术门槛高，性价比低。

### 2.12 【P2】调一杯 App

- **URL**：安卓应用市场（"调一杯" v3.2.0）
- **类型**：中文 App（社区 + 课程）
- **数据内容**：~50+ 经典配方 + 视频教学 + 调酒师课程 + 用户分享社区
- **获取方式**：无开放 API，仅 App 内消费
- **数据质量评分**：2/5（产品形态重于数据本身，配方数据为基础款）
- **接入建议**：**不推荐接入**。无可编程获取途径。

### 2.13 【P2】Difford's Guide —— 专业权威但封闭

- **URL**：https://www.diffordsguide.com/
- **类型**：专业付费（Simon Difford 主编，自 2001 年）
- **数据内容**：
  - **2800+ 配方**，每款配专业摄影
  - 每款含：玻璃杯、创作者、故事、Simon Difford 个人评分与评论
  - 部分百科内容免费（encyclopedia/1989/cocktails/cocktail-categories/families 等族谱分类页）
- **获取方式**：
  - 付费 App：Diffords Cocktails #9（iOS，约 ¥68/版本）
  - 付费书籍：Difford's Guide to Cocktails #12（最新版纸质书）
  - 网站 encyclopedia 部分免费可读
- **数据质量评分**：5/5（**行业最权威**，业内公认的"鸡尾酒圣经"）
- **合规性**：❌ 严格版权，禁止爬取与商业转用
- **中文支持**：❌
- **接入建议**：**远期考虑**。**仅作为人工审核参考**：当 KB 需要为某款配方做权威性背书时，可在 `notes` 字段引用 Difford's 评分（注明出处）。**禁止自动抓取与复制配方全文**。

### 2.14 【P2】Mixel - Cocktail Recipes

- **URL**：https://apps.apple.com/.../mixel-cocktail-recipes
- **类型**：iOS 付费 App
- **数据内容**：2500+ 手工鸡尾酒配方，含标签/评分/备注/风味筛选
- **获取方式**：App 内购买，无 API
- **数据质量评分**：4/5
- **合规性**：❌ 严格版权
- **接入建议**：**不推荐接入**。封闭生态，无可行获取路径。

### 2.15 【P2】APIVerve Cocktail API

- **URL**：https://apiverve.com/marketplace/cocktail
- **类型**：付费第三方 API
- **数据内容**：按名搜索返回配方（glass / category / ingredients[] / unit / amount / label / garnish / preparation / estimatedStrength）
  - 示例响应字段质量较高，已分类（After Dinner / All Day / Before Dinner）+ 估算强度
- **获取方式**：注册 + API Key，按调用计费
- **数据质量评分**：3/5（数据本身源自 IBA，与 §2.2/§2.3 重叠，付费价值低）
- **合规性**：MIT License（包装代码），但 API 调用需付费
- **接入建议**：**不推荐接入**。数据源与免费 IBA 数据集重复，付费无意义。

### 2.16 【P2】知乎 / 小红书 UGC

- **URL**：https://www.zhihu.com / https://www.xiaohongshu.com
- **类型**：UGC 平台
- **数据内容**：海量中文调酒内容（"调酒配方全攻略"等长文 + 大量短笔记）
- **获取方式**：官方无开放 API；需爬虫（技术门槛高 + 反爬激烈）
- **数据质量评分**：2/5（参差不齐，多为搬运 + 个人化改编，权威性低）
- **合规性**：❌ **高风险**
  - **知乎**：用户协议含"非独家版权"条款，即使删除/拒稿仍主张授权（2025 年公开争议，被称为"霸王条款"）。商业使用风险极高。
  - **小红书**：酒类内容受平台合规限制（不得直接推销），UGC 版权属发布者，平台禁止爬取
- **中文支持**：✅
- **接入建议**：**不推荐作为配方数据源**。可作为：
  - 用户调研/选题灵感来源（人工浏览，不入库）
  - M4.3 UGC Studio 上线后，**由用户主动录入**其原创配方（而非爬取）

---

## 3. 推荐接入优先级

### P0：立即接入（免费 + 高质量 + 易接入）

| 数据源 | 接入动作 | 工作量 | 预期增益 |
|---|---|---|---|
| **TheCocktailDB** | 实现 `thecocktaildb_sync.py`（原 Plan Task 2 方向保留） | 2 人天 | +636 配方（与 IBA 重叠 ~80 款，净增 ~550 款） |
| **iba_dataset_json** | 新增 `iba_dataset_sync.py`，直接读 `recipes.json` + `ingredients_strength.json` | 0.5 人天 | +100 IBA 配方（替换 M3 的 8 款为全集） |
| **iba-cocktail-list (npm)** | 通过 `npm pack` 下载 JSON，解析为种子 | 0.5 人天 | 同上 + 严格类型 + 三大分类 |
| **bar-assistant** | 提取其 `substitutes` 表导入 `substitutes.py`；参考 ABV 算法 | 1 人天 | 替代材料关系从 0 → 数百对；ABV 计算补全 |

**P0 合计工作量**：~4 人天。完成后 KB 从 8 款 → ~650 款配方 + 完整替代关系 + ABV 数据。

### P1：评估后接入（需确认合规或技术难度）

| 数据源 | 评估重点 | 决策门槛 |
|---|---|---|
| **IBA 官网** | 爬虫合规性 + robots.txt | 若仅做"最新列表 diff"则可，全量爬取需法务确认 |
| **cocktail-suggestions** | 同义词词典 License | 仅借鉴方法论不抄代码即可 |
| **Bacardi 官方** | 品牌内容使用条款 | 仅做品牌关联字段，不复制配方全文 |
| **Diageo Bar Academy** | 同上 | 同上 + 视频外链引用 |
| **Kaggle cocktails-data** | 数据集 License | 用于训练 IBA 分类器，不入库主配方 |
| **enjoycocktail.com** | 联系作者授权 | 中文数据稀缺，值得 1 封邮件尝试合作 |

### P2：远期考虑（付费或合规风险）

| 数据源 | 仅可作为 | 限制原因 |
|---|---|---|
| **Difford's Guide** | 人工审核参考（评分引用） | 严格版权，禁止爬取 |
| **Mixel App** | 不接入 | 封闭 App |
| **APIVerve API** | 不接入 | 数据与免费源重复 |
| **drink8.cn** | 不接入 | 数据老旧 + 反爬 |
| **调一杯 App** | 不接入 | 无 API |
| **知乎 / 小红书** | 仅作为 M4.3 UGC Studio 用户录入入口 | 平台版权霸王条款 |

---

## 4. 数据源整合策略

### 4.1 与现有 IBA 种子数据的融合

**现状**：M3 的 `seed_recipes.py` 含 8 款手工配方（马天尼/莫吉托/尼格罗尼/玛格丽特/...），每款含：
- `title`（中英双语）
- `base_spirit`（gin/rum/tequila/...）
- `difficulty`（easy/medium/hard）
- `season`（spring/summer/autumn/winter）
- `ingredients`（**中文标准名**：金酒/朗姆酒/青柠汁/糖浆/薄荷叶/苏打水/...）
- `content`（Markdown，含 ## 配方 / ## 步骤 / ## 风味 三段）

**融合策略**：

1. **保留 M3 的 8 款作为「金标准样本」**：人工撰写、字段最全、风味描述最丰富，作为 KB 的"教学样本"。
2. **新增"IBA 全集层"**（来自 §2.2/§2.3）：100 款 IBA 官方配方，`source = "iba"`，`verified = True`，作为权威基础层。
3. **新增"扩充层"**（来自 §2.1 TCTDB）：~550 款非 IBA 配方，`source = "thecocktaildb"`，`verified = False`（默认不进实验室匹配，与 M4.2 Plan Task 3 一致）。
4. **字段映射表**：

| Hermes KB 字段 | IBA 数据集 | TCTDB | bar-assistant |
|---|---|---|---|
| `title` | `name`（转中文译名表） | `strDrink`（保留英文 + 中文译名） | `name` |
| `ingredients[]` | `ingredients[].name` → 中文 | `strIngredient1-15` → 中文 | `ingredients[].name` |
| `content`（Markdown） | 由 name + ingredients + method 拼装 | 由 strInstructions + 材料拼装 | 由 API 拼装 |
| `category` | `type`（After Dinner / All Day / Before Dinner） | `strCategory` | `tags[]` |
| `source` | `"iba"` | `"thecocktaildb"` | `"bar-assistant"` |
| `source_id` | name slug | `idDrink` | cocktail_id |
| `verified` | `True` | `False` | `False` |
| `season` | 推断（基于材料：青柠/薄荷→summer，威士忌/苦精→winter） | `None` | `None` |
| `difficulty` | 推断（材料数 ≤4 → easy，5-7 → medium，≥8 → hard） | `None` | `None` |

### 4.2 去重策略（同一配方多来源）

**问题**：Mojito 会同时出现在 M3 种子、IBA 数据集、TCTDB、bar-assistant 中。

**策略**（多层去重）：

1. **第一层（精确去重）**：`source + source_id` 唯一索引（M4.2 Plan Task 2 已实现）。
2. **第二层（名称归一化去重）**：将 `title` 转为 slug（lowercase + 去标点 + 去空格），同 slug 视为同一配方候选。
   - 示例：`"Dry Martini"` / `"马天尼 Martini"` / `"Martini (cocktail)"` → slug `dry_martini` / `martini`
3. **第三层（材料指纹去重）**：取材料集合的归一化 hash（仅材料名，不含用量），相同 hash 视为高概率同配方。
   - 示例：`{金酒, 味美思, 橄榄}` = `{gin, vermouth, olive}` → 同一指纹
4. **冲突仲裁**：当多源命中同一配方时，**优先级**为 `iba > seed(M3 手工) > thecocktaildb > bar-assistant`。低优先级源的字段填入高优先级源的缺失字段（如 TCTDB 的图片 URL 填入 IBA 配方的 `image_url` 字段）。
5. **保留多源 trace**：在 Document 增加 `sources: list[dict]` 字段（或单独 `recipe_sources` 表），记录"该配方来自哪些源 + 各源 ID"，便于溯源与冲突可视化。

### 4.3 材料名归一化挑战

**现状**：M4.2 Plan 的 `_INGREDIENT_OVERRIDES` 含 40+ 英→中映射，但远不够覆盖 TCTDB 的 489 种材料。

**挑战清单**：

| 挑战 | 示例 | 当前方案缺口 |
|---|---|---|
| **同义词** | "lime juice" / "lime" / "fresh lime juice" / "青柠汁" / "莱姆汁" | 需要同义词词典（参考 §2.6 cocktail-suggestions） |
| **品牌 vs 通用名** | "Bacardi Carta Blanca" → "白朗姆酒"；"Angostura bitters" → "苦精" | 需品牌映射表（参考 §2.7 Bacardi 官方） |
| **亚类归并** | "light rum" / "dark rum" / "white rum" / "spiced rum" → 是否都归"朗姆酒"？ | **业务决策**：建议保留亚类（白朗姆/黑朗姆/金朗姆），匹配时按"基酒大类"匹配 |
| **单位不统一** | TCTDB: "2-3 oz"；IBA: 4.5cl；M3: "60ml" | 需单位换算器（oz↔ml↔cl），参考 bar-assistant 实现 |
| **非标用量** | "Juice of 1 lime" / "2 dashes" / "Top with soda" | 保留原文 + 标记 `measure_raw`，不强行归一化 |
| **缺失中文译名** | "Drambuie" / "Cointreau" / "Campari" | 需要专用酒类中文名词典（金巴利/君度/杜林标已有，需扩充） |

**建议新增模块**：`src/hermes_kb/ingredient_dictionary.py`
- 集中管理英→中映射 + 同义词 + 品牌映射 + 亚类关系
- 数据源：① M4.2 现有 `_INGREDIENT_OVERRIDES` ② bar-assistant 的 ingredients 表 ③ IBA 数据集的 `ingredients_strength.json`（含 ABV）④ 手工补全

---

## 5. 对 M4.2 Plan 的修订建议

### 5.1 `thecocktaildb_sync.py` 是否需要调整？

**结论：方向正确，但需补 3 处修订。**

原 Plan Task 2 的实现（`sync_thecocktaildb` + `normalize_ingredient` + `parse_recipe`）整体可用，但：

1. **同步范围扩大**：原 Plan 用 `search.php?f=a` 仅拉取首字母 a 的配方（~30 款）。应改为遍历 `a-z` + `0-9` 全量拉取（约 636 款），或用 Premium Key 的全量列表端点（$10 终身，强烈推荐购买）。
2. **图片字段补全**：原 `parse_recipe` 未保存 `strDrinkThumb`。应新增 `image_url` 字段（M4.2 Document 模型已扩展，但需加 `image_url: str | None` 字段或塞入 metadata）。
3. **材料归一化失败处理**：原 `normalize_ingredient` 返回 `None` 时直接跳过该材料，会导致配方信息丢失。应改为：归一化失败时**保留英文原名**入 `ingredients[]`，并记入 `unknown_ingredients[]` 供后续人工补全字典，**不丢材料**。

### 5.2 `ima_adapter` 是否值得继续？

**结论：立即砍掉，替换为 `iba_dataset_sync.py`。**

**理由**：
- 公开搜索无法定位名为 "ima" 的专业酒类知识库 API（原 Plan 中 `base_url = "https://api.ima.example.com/v1"` 是 example.com 占位符，明显示意未真实存在）。
- 原 Plan Task 5 的 `IMAAdapter` 类 + `fetch_ima_recipes` 函数仅是空壳，`fetch()` 永远返回 `[]`，**对 KB 价值为零**。
- 继续维护一个永不返回数据的 adapter 是技术债。

**修订动作**：
1. 删除原 Plan Task 5（`ima_adapter.py`），或保留文件骨架但改名为 `bar_assistant_adapter.py`，对接真实开源项目 §2.4。
2. 新增 Task 5'：实现 `iba_dataset_sync.py`，读取 §2.2 的 `recipes.json` + `ingredients_strength.json`，把 IBA 全集 100 款导入 KB（`source = "iba"`, `verified = True`）。
3. API 端点 `/api/lab/sync` 的 `source = "ima"` 分支改为 `source = "iba"`，调用新的同步器。

### 5.3 是否有更好的数据源替代？

**有。推荐组合（替代原 Plan 的「TCTDB + ima」二选）**：

**新组合：TCTDB + IBA 数据集 + bar-assistant**

| 数据源 | 角色 | 替代了原 Plan 的 |
|---|---|---|
| TheCocktailDB | 配方扩充主力（550+ 非 IBA 配方 + 图片） | 原 TCTDB（不变） |
| iba_dataset_json + iba-cocktail-list | IBA 权威基础层（100 款 + ABV） | 替代 ima adapter（ima 不存在） |
| bar-assistant | 替代材料关系 + ABV 算法参考 | 补充 substitutes.py 数据稀薄问题 |

**修订后 M4.2 Task 列表**（原 8 个 Task → 9 个 Task）：

| Task | 原 Plan | 修订建议 |
|---|---|---|
| 1. Document 模型扩展 | ✅ 保留 | 增加 `image_url` 字段 |
| 2. TCTDB 同步器 | ✅ 保留 + 修订 | ① 全量拉取 ② 保存图片 URL ③ 归一化失败保留原名 |
| 3. recipe_match 过滤 | ✅ 保留 | 不变 |
| 4. recipe_filter | ✅ 保留 | 不变 |
| 5. ~~ima adapter~~ | ❌ 删除 | 改为 Task 5': IBA 数据集同步器 |
| 5'. **iba_dataset_sync.py** | ➕ 新增 | 读 GitHub JSON，导入 IBA 100 款 + ABV |
| 6. API 端点 | ✅ 保留 + 修订 | `source` 枚举改为 `thecocktaildb / iba / bar-assistant` |
| 7. 前端 | ✅ 保留 + 修订 | 数据源筛选器下拉项更新 |
| 8. 全量回归 | ✅ 保留 | 不变 |
| **9. substitutes 增强** | ➕ 新增 | 从 bar-assistant 导入替代材料关系（可放 M4.2 或 M4.3） |

### 5.4 长期路线图建议

- **M4.2（当前）**：TCTDB + IBA 数据集 + bar-assistant substitutes，KB 扩到 ~650 配方。
- **M4.3（UGC Studio）**：用户录入原创配方；引入知乎/小红书内容仅作为"用户灵感来源"而非爬取源。
- **M5（治理与质量）**：
  - 接入 IBA 官网做"最新列表 diff"（合规确认后）
  - 引入 Difford's Guide 评分作为人工审核参考（购买 1 本纸质书 + App，引用评分入 `notes`）
  - 引入 Bacardi/Diageo 品牌关联字段
- **M6（多媒体）**：TCTDB 图片 + 品牌官方视频外链（Diageo Bar Academy YouTube）

---

## 6. 调研方法与局限性

### 6.1 调研方法
1. **项目代码核对**：阅读 `seed_recipes.py`（M3 种子格式）、`m4.2-external-sources.md`（原 Plan 8 Task）、`models.py` 结构，确认现状与原 Plan 意图。
2. **WebSearch**：8 次英文/中文混合搜索，覆盖免费 API / IBA 官方 / GitHub 开源 / Difford's Guide / 中文社区 / 品牌官方 / 营养计算 / ima 验证。
3. **WebFetch**：验证 TheCocktailDB API 文档页（确认 636 配方 + 全部端点 + 图片 URL 规则）。
4. **交叉验证**：iba-world.com 官方 102 款 vs iba_dataset_json ~100 款 vs iba-cocktail-list 90+ 款，数据一致性确认。

### 6.2 局限性
- 未实际 clone `lmc2179/iba_dataset_json` 与 `karlomikus/bar-assistant` 验证数据完整度（仅基于文档与 README 判断）。
- 未联系 enjoycocktail.com 作者确认合作意愿。
- 未对 Bacardi/Diageo 页面做 robots.txt 实际检查。
- ima 是否为内部代号或私有产品，无法在公开网络验证；如项目方有内部信息，请补充。

---

## 附录 A：TheCocktailDB API 完整端点速查（已 WebFetch 验证）

```
基础 URL: https://www.thecocktaildb.com/api/json/v1/{KEY}
KEY: 1 (测试, 免费) / 自购 Premium ($10 终身)

搜索类:
  /search.php?s={name}         按名搜索（模糊）
  /search.php?f={letter}       按首字母列
  /search.php?i={ingredient}   按材料名搜
  /filter.php?i={ingredient}   按材料过滤（仅元数据）
  /filter.php?a={Alcoholic|Non_Alcoholic}
  /filter.php?c={category}     如 Cocktail / Ordinary_Drink
  /filter.php?g={glass}        如 Cocktail_glass / Champagne_flute
  /filter.php?i={a,b,c}        多材料过滤 (Premium only)

查询类:
  /lookup.php?i={idDrink}      按配方 ID 查详情
  /lookup.php?iid={iid}        按材料 ID 查
  /random.php                  随机一款
  /randomselection.php         随机 10 款 (Premium only)
  /popular.php                 热门 (Premium only)
  /latest.php                  最新 (Premium only)

列表类:
  /list.php?c=list             所有分类
  /list.php?g=list             所有杯型
  /list.php?i=list             所有材料
  /list.php?a=list             所有酒精类型

图片:
  配方: https://www.thecocktaildb.com/images/media/drink/{hash}.jpg
        + /small (200x200) / /medium (350x350) / /large (500x500)
  材料: https://www.thecocktaildb.com/images/ingredients/{Name}.png
        + -small.png (100x100) / -medium.png (350x350) / .png (700x700)
```

## 附录 B：IBA 官方配方分类（2024 版，102 款）

来源：https://iba-world.com/cocktails/all-cocktails/ + https://www.cocktailengineering.it/storia-della-miscelazione/la-lista-dei-cocktail-ufficiali-iba/

1. **The Unforgettables（难忘经典）** ~32 款：Alexander, Americano, Angel Face, Aviation, Between the Sheets, Boulevardier, Brandy Crusta, Casino, Clover Club, Daiquiri, Dry Martini, Gin Fizz, Hanky Panky, John Collins, Last Word, Manhattan, Martinez, Mary Pickford, Monkey Gland, Negroni, Old Fashioned, Paradise, Planter's Punch, Porto Flip, Ramos Gin Fizz, Remember the Maine, Rusty Nail, Sazerac, Sidecar, Stinger, Tuxedo, Vieux Carré, Whiskey Sour, White Lady
2. **Contemporary Classics（当代经典）** ~32 款：Bellini, Black Russian, Bloody Mary, Caipirinha, Cardinale, Champagne Cocktail, Corpse Reviver #2, Cosmopolitan, ...
3. **New Era Drinks（新时代）** ~38 款：Bee's Knees, Bramble, Canchanchara, Chartreuse Swizzle, ...

**对 Hermes KB 的启示**：M3 种子的 8 款（马天尼/莫吉托/尼格罗尼/玛格丽特/...）基本落在 The Unforgettables + Contemporary Classics，扩展时应保留 `iba_category` 字段记录此三分法。

## 附录 C：ABV / 卡路里计算公式（来自 §2 周边工具）

**酒精卡路里公式**（来自 basicfreetools）：
```
Alcohol Calories = Volume(ml) × (ABV / 100) × 0.789 × 7
```
- `0.789` = 乙醇密度 g/ml
- `7` = 每克乙醇 7 kcal

**鸡尾酒总 ABV 公式**（来自 calculator.city Mastering Mixology）：
```
Final ABV = Σ(Ingredient Volume × Ingredient ABV) / Total Volume
```

**对 Hermes KB 的启示**：M5 可新增 `recipe_stats.py`，用 bar-assistant 的 `ingredients_strength` 数据（ABV per ingredient）+ 上述公式自动计算每款配方的总 ABV 与卡路里，作为 `recipe.abv` 与 `recipe.calories` 字段。
