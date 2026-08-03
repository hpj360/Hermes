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

## Related skills

- **tavily-search**: AI 优化的搜索（返回结构化 JSON，含 score 排序）。当 brave-search 结果噪音大或需要相关度排序时降级到 tavily-search。
- **agent-browser**: 需要交互式浏览（登录、点击、滚动）时使用，brave-search 只做无浏览器搜索。
- **summarize**: 需要对搜索到的 URL 做摘要提取时使用，brave-search 的 `--content` 只提取正文不做摘要。
