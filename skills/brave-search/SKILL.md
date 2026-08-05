---
name: brave-search
description: Web search and content extraction via Brave Search API. Use for searching documentation, facts, or any web content. Lightweight, no browser required.
---

# Brave Search

Headless web search and content extraction using Brave Search. No browser required.

## Setup

Run once before first use:

```bash
cd ~/Projects/agent-scripts/skills/brave-search
npm ci
```

Needs env: `BRAVE_API_KEY`.

## Search

```bash
./search.js "query"                    # Basic search (5 results)
./search.js "query" -n 10              # More results
./search.js "query" --content          # Include page content as markdown
./search.js "query" -n 3 --content     # Combined
```

## Extract Page Content

```bash
./content.js https://example.com/article
```

Fetches a URL and extracts readable content as markdown.

## Output Format

```
--- Result 1 ---
Title: Page Title
Link: https://example.com/page
Snippet: Description from search results
Content: (if --content flag used)
  Markdown content extracted from the page...

--- Result 2 ---
...
```

## When to Use

- Searching for documentation or API references
- Looking up facts or current information
- Fetching content from specific URLs
- Any task requiring web search without interactive browsing

## 搜索 skill 路由规则（统一）

当用户说"搜索""查一下""找找"时，按以下优先级选择：

```
默认：brave-search（轻量、免费额度高、无浏览器依赖）
  → 结果噪音大 / 需要相关度 score 排序 / 需要 --deep 深度研究 / 需要 --topic news 新闻搜索
      升级到：tavily-search
  → 需要登录 / 需要 JS 执行 / 需要点击滚动
      升级到：agent-browser
  → 需要对搜到的 URL 做 AI 摘要（而非仅提取正文）
      升级到：summarize
```

**禁止**：不要把 tavily-search 作为 brave-search 的"降级方案"，也不要把 brave-search 作为 tavily-search 的"降级方案"。两者是**默认 → 质量升级**的单向关系，不是互为降级。

## Related skills

- **tavily-search**: 质量升级路径。返回结构化 JSON + score 排序，支持 `--deep` 深度搜索和 `--topic news` 新闻搜索。当 brave-search 结果噪音大、需要相关度排序、或需要深度研究时**升级**到 tavily-search。**不是互为降级**。
- **agent-browser**: 需要交互式浏览（登录、点击、滚动）时使用，brave-search 只做无浏览器搜索。
- **summarize**: 需要对搜索到的 URL 做摘要提取时使用，brave-search 的 `--content` 只提取正文不做摘要。
