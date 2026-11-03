import { useEffect, useState } from "react";
import { get, post } from "../api";
import type { RetrospectiveResponse } from "../types";

interface Health {
  status: string;
  scheduler?: {
    queue_depth: number;
    jobs_active: number;
    workers?: { active: number; size: number; running: boolean };
    cron?: boolean;
  };
}

interface Todo {
  todo_id: string;
  title: string;
  type: string;
  status: string;
  job_id?: string;
}

interface Job {
  job_id: string;
  status: string;
  target_project: string;
  created_at?: string;
}

interface Episode {
  id?: string;
  kind?: string;
  summary?: string;
  created_at?: string;
}

interface SearchResult {
  episode?: Episode;
  score?: number;
}

function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => get<Health>("/health", { wb: true }).then((h) => alive && setHealth(h)).catch(() => alive && setHealth(null));
    load();
    const t = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  return health;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}
      title={ok ? "healthy" : "unhealthy"}
    />
  );
}

const SOURCE_LABELS: Record<string, string> = {
  adapter: "真实回采",
  manual: "人工回填",
  simulation: "模拟",
};

function RetrospectiveCard() {
  const [retro, setRetro] = useState<RetrospectiveResponse | null>(null);
  const [days, setDays] = useState(7);

  useEffect(() => {
    let alive = true;
    get<RetrospectiveResponse>(`/analytics/retrospective?days=${days}`)
      .then((d) => alive && setRetro(d))
      .catch(() => alive && setRetro(null));
    return () => {
      alive = false;
    };
  }, [days]);

  const delta = (cur: number, prev: number) => {
    if (prev === 0) return cur > 0 ? `+${cur}` : "—";
    const pct = Math.round(((cur - prev) / prev) * 100);
    return `${pct >= 0 ? "+" : ""}${pct}%`;
  };
  const deltaCls = (cur: number, prev: number) =>
    cur >= prev ? "text-green-600" : "text-red-600";

  const interactions = (s: RetrospectiveResponse["period"]) =>
    s.total_likes + s.total_comments + s.total_shares;

  return (
    <div className="bg-white border rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold">内容复盘</h2>
        <div className="flex gap-1">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-2 py-0.5 rounded text-xs ${
                days === d ? "bg-slate-900 text-white" : "bg-gray-100 text-gray-600"
              }`}
            >
              {d}天
            </button>
          ))}
        </div>
      </div>
      {!retro ? (
        <p className="text-sm text-gray-400">复盘数据不可达</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3 text-center">
            {(
              [
                ["浏览", retro.period.total_views, retro.previous_period.total_views],
                ["点赞", retro.period.total_likes, retro.previous_period.total_likes],
                [
                  "总互动",
                  interactions(retro.period),
                  interactions(retro.previous_period),
                ],
              ] as [string, number, number][]
            ).map(([label, cur, prev]) => (
              <div key={label} className="bg-gray-50 rounded p-3">
                <div className="text-2xl font-bold">{cur}</div>
                <div className="text-xs text-gray-500">
                  {label}（{retro.days}天）
                </div>
                <div className={`text-xs font-medium ${deltaCls(cur, prev)}`}>
                  vs 上期 {delta(cur, prev)}
                </div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-1 text-xs">
            {Object.entries(retro.source_counts).map(([src, cnt]) => (
              <span
                key={src}
                className={`rounded px-1.5 py-0.5 ${
                  src === "adapter"
                    ? "bg-green-100 text-green-700"
                    : src === "manual"
                      ? "bg-blue-100 text-blue-700"
                      : "bg-gray-100 text-gray-600"
                }`}
              >
                {SOURCE_LABELS[src] ?? src} ×{cnt}
              </span>
            ))}
            {Object.keys(retro.source_counts).length === 0 && (
              <span className="text-gray-400">本期无数据回填</span>
            )}
          </div>

          {retro.top_contents.length > 0 && (
            <div>
              <h3 className="text-xs text-gray-500 mb-1">互动 Top 5</h3>
              <ul className="space-y-1">
                {retro.top_contents.map((t) => (
                  <li
                    key={t.content_id}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="truncate pr-2">{t.title}</span>
                    <span className="text-xs text-gray-500 whitespace-nowrap">
                      互动{t.interactions} · 浏览{t.views}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const health = useHealth();
  const [todos, setTodos] = useState<Todo[]>([]);
  const [attention, setAttention] = useState<Job[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [capture, setCapture] = useState("");
  const [search, setSearch] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);

  const refresh = () => {
    get<{ todos: Todo[] }>("/todos", { wb: true }).then((d) => setTodos(d.todos)).catch(() => {});
    get<{ jobs: Job[] }>("/jobs", { wb: true })
      .then((d) =>
        setAttention(
          d.jobs.filter((j) => ["QUEUED", "RUNNING", "PENDING", "FAILED"].includes(j.status)).slice(0, 5),
        ),
      )
      .catch(() => {});
    get<{ episodes: Episode[] }>("/memory/episodes", { wb: true })
      .then((d) => setEpisodes((d.episodes ?? []).slice(0, 5)))
      .catch(() => {});
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onCapture = async () => {
    const title = capture.trim();
    if (!title) return;
    setCapture("");
    try {
      await post("/todos", { title, type: "todo", source: "inbox" }, { wb: true });
      refresh();
    } catch (e) {
      alert(`捕获失败: ${(e as Error).message}`);
    }
  };

  const onSearch = async () => {
    const q = search.trim();
    if (!q) return;
    try {
      const data = await get<{ results: SearchResult[] }>(`/memory/search?q=${encodeURIComponent(q)}`, { wb: true });
      setSearchResults(data.results ?? []);
    } catch {
      setSearchResults([]);
    }
  };

  const healthy = health?.status === "ok";
  const activeJobs = health?.scheduler?.jobs_active ?? attention.length;

  return (
    <div>
      {/* 顶栏：健康点 + 运行中 job 数 + 捕获条 + 全局搜索 */}
      <div className="flex items-center gap-3 bg-white border rounded-lg p-3 mb-4">
        <StatusDot ok={!!healthy} />
        <span className="text-sm text-gray-600">
          {healthy ? "系统正常" : "服务不可达"} · 运行中 {activeJobs} · 队列 {health?.scheduler?.queue_depth ?? "-"}
        </span>
        <input
          className="flex-1 border rounded px-3 py-1.5 text-sm"
          placeholder="快速捕获：记一条灵感 / 存链接…"
          value={capture}
          onChange={(e) => setCapture(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onCapture()}
        />
        <button className="px-3 py-1.5 rounded bg-slate-900 text-white text-sm" onClick={onCapture}>
          记一笔
        </button>
        <div className="flex items-center gap-2">
          <input
            className="border rounded px-3 py-1.5 text-sm w-48"
            placeholder="全局搜索…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
          />
          <button className="px-3 py-1.5 rounded bg-gray-100 text-sm" onClick={onSearch}>
            搜索
          </button>
        </div>
      </div>

      {/* 搜索结果显示 */}
      {search && (
        <div className="bg-white border rounded-lg p-4 mb-4">
          <h3 className="text-sm font-semibold mb-2">搜索 “{search}”</h3>
          {searchResults.length === 0 ? (
            <p className="text-sm text-gray-500">无结果</p>
          ) : (
            <ul className="space-y-1">
              {searchResults.map((r, i) => (
                <li key={i} className="text-sm text-gray-700">
                  {r.episode?.summary ?? "（无摘要）"}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        {/* 左 60%：今日简报 + 活动流 */}
        <div className="col-span-7 space-y-4">
          <div className="bg-white border rounded-lg p-4">
            <h2 className="font-semibold mb-3">今日简报</h2>
            <div className="grid grid-cols-4 gap-3 text-center">
              {[
                ["完成任务", attention.filter((j) => j.status === "SUCCEEDED").length, "text-green-600"],
                ["需关注", attention.filter((j) => ["FAILED", "QUEUED", "RUNNING"].includes(j.status)).length, "text-red-600"],
                ["待办", todos.length, "text-blue-600"],
                ["新记忆", episodes.length, "text-purple-600"],
              ].map(([label, value, cls]) => (
                <div key={label as string} className="bg-gray-50 rounded p-3">
                  <div className={`text-2xl font-bold ${cls}`}>{value}</div>
                  <div className="text-xs text-gray-500">{label}</div>
                </div>
              ))}
            </div>
            {todos.length === 0 && attention.length === 0 && (
              <p className="text-sm text-gray-400 mt-4">
                还没有待办与任务。用上方捕获条记一条，或到「任务运行」提交一个 job。
              </p>
            )}
          </div>

          <div className="bg-white border rounded-lg p-4">
            <h2 className="font-semibold mb-2">最近活动</h2>
            {episodes.length === 0 ? (
              <p className="text-sm text-gray-400">暂无活动记录</p>
            ) : (
              <ul className="space-y-1">
                {episodes.map((e) => (
                  <li key={e.id ?? e.created_at ?? String(Math.random())} className="text-sm text-gray-700">
                    <span className="text-xs text-gray-400">{e.kind}</span> {e.summary}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <RetrospectiveCard />
        </div>

        {/* 右 40%：待我处理（待办 + 需关注 jobs） */}
        <div className="col-span-5 space-y-4">
          <div className="bg-white border rounded-lg p-4">
            <h2 className="font-semibold mb-3">待办</h2>
            {todos.length === 0 ? (
              <p className="text-sm text-gray-400">无待办。可勾选完成，或到「捕获」页添加。</p>
            ) : (
              <ul className="space-y-1">
                {todos.map((t) => (
                  <li key={t.todo_id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={t.status === "DONE"}
                      onChange={async () => {
                        const next = t.status === "DONE" ? "PENDING" : "DONE";
                        await post(`/todos/${t.todo_id}/status`, { status: next }, { wb: true }).catch(() => {});
                        refresh();
                      }}
                    />
                    <span className={t.status === "DONE" ? "line-through text-gray-400" : ""}>{t.title}</span>
                    {t.job_id && <span className="text-xs text-blue-600">→ job</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="bg-white border rounded-lg p-4">
            <h2 className="font-semibold mb-3">需关注 Jobs</h2>
            {attention.length === 0 ? (
              <p className="text-sm text-gray-400">当前无进行中或失败的任务。</p>
            ) : (
              <ul className="space-y-1">
                {attention.map((j) => (
                  <li key={j.job_id} className="flex items-center justify-between text-sm">
                    <span className="font-mono text-xs">{j.job_id.slice(0, 8)}</span>
                    <span className="text-gray-600">{j.target_project}</span>
                    <span className="px-2 py-0.5 rounded text-xs bg-gray-100">{j.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
