#!/usr/bin/env node
// 输出契约与 content-extraction 统一报告结构对齐（# 标题 + > 元信息行 + --- + 正文）。
// 机器模式：--json。

function usage() {
  console.error(`Usage: search.mjs "query" [-n 5] [--deep] [--topic general|news] [--days 7] [--json]`);
  process.exit(2);
}

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === "-h" || args[0] === "--help") usage();

const query = args[0];
let n = 5;
let searchDepth = "basic";
let topic = "general";
let days = null;
let jsonMode = false;

for (let i = 1; i < args.length; i++) {
  const a = args[i];
  if (a === "-n") {
    n = Number.parseInt(args[i + 1] ?? "5", 10);
    i++;
    continue;
  }
  if (a === "--deep") {
    searchDepth = "advanced";
    continue;
  }
  if (a === "--topic") {
    topic = args[i + 1] ?? "general";
    i++;
    continue;
  }
  if (a === "--days") {
    days = Number.parseInt(args[i + 1] ?? "7", 10);
    i++;
    continue;
  }
  if (a === "--json") {
    jsonMode = true;
    continue;
  }
  console.error(`Unknown arg: ${a}`);
  usage();
}

const apiKey = (process.env.TAVILY_API_KEY ?? "").trim();
if (!apiKey) {
  console.error("Missing TAVILY_API_KEY");
  process.exit(1);
}

const body = {
  api_key: apiKey,
  query: query,
  search_depth: searchDepth,
  topic: topic,
  max_results: Math.max(1, Math.min(n, 20)),
  include_answer: true,
  include_raw_content: false,
};

if (topic === "news" && days) {
  body.days = days;
}

const resp = await fetch("https://api.tavily.com/search", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
  },
  body: JSON.stringify(body),
});

if (!resp.ok) {
  const text = await resp.text().catch(() => "");
  throw new Error(`Tavily Search failed (${resp.status}): ${text}`);
}

const data = await resp.json();

const results = (data.results ?? []).slice(0, n);

// 机器模式：原始 JSON 直出
if (jsonMode) {
  console.log(JSON.stringify({ query, answer: data.answer ?? null, results }, null, 2));
  process.exit(0);
}

// 人类模式：统一报告结构（# 标题 + > 元信息行 + --- + 正文）
console.log(`# 搜索: ${query}\n`);
console.log(`> 来源: Tavily | 深度: ${searchDepth} | 主题: ${topic} | 结果数: ${results.length}\n`);
console.log("---\n");

if (data.answer) {
  console.log("## Answer\n");
  console.log(data.answer);
  console.log("\n---\n");
}

console.log("## Sources\n");

for (const r of results) {
  const title = String(r?.title ?? "").trim();
  const url = String(r?.url ?? "").trim();
  const content = String(r?.content ?? "").trim();
  const score = r?.score ? ` (relevance: ${(r.score * 100).toFixed(0)}%)` : "";

  if (!title || !url) continue;
  console.log(`- **${title}**${score}`);
  console.log(`  ${url}`);
  if (content) {
    console.log(`  ${content.slice(0, 300)}${content.length > 300 ? "..." : ""}`);
  }
  console.log();
}
