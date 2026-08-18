import { useEffect, useState } from "react";
import { get } from "../api";

interface Fact {
  key: string;
  value: string;
}

interface Episode {
  id?: string;
  kind?: string;
  summary?: string;
  details?: unknown;
  created_at?: string;
}

interface SearchResult {
  episode?: Episode;
  score?: number;
}

export default function MemoryPage() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [tab, setTab] = useState<string>("episodes");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);

  const refresh = () => {
    get<{ facts: Fact[] }>("/memory/facts", { wb: true })
      .then((d) => setFacts(d.facts ?? []))
      .catch(() => {});
    get<{ episodes: Episode[] }>("/memory/episodes", { wb: true })
      .then((d) => setEpisodes(d.episodes ?? []))
      .catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, []);

  const search = async () => {
    const query = q.trim();
    if (!query) return;
    try {
      const d = await get<{ results: SearchResult[] }>(`/memory/search?q=${encodeURIComponent(query)}`, { wb: true });
      setResults(d.results ?? []);
      setTab("search");
    } catch {
      setResults([]);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        {["episodes", "facts", "search"].map((t) => (
          <button
            key={t}
            className={`px-3 py-1.5 rounded text-sm ${tab === t ? "bg-slate-900 text-white" : "bg-gray-100"}`}
            onClick={() => setTab(t)}
          >
            {t === "episodes" ? "情景 Episodes" : t === "facts" ? "事实 Facts" : "检索"}
          </button>
        ))}
      </div>

      {tab === "search" && (
        <div className="bg-white border rounded-lg p-4 mb-4">
          <div className="flex gap-2">
            <input
              className="flex-1 border rounded px-3 py-1.5 text-sm"
              placeholder="检索记忆…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
            />
            <button className="px-4 py-1.5 rounded bg-slate-900 text-white text-sm" onClick={search}>
              检索
            </button>
          </div>
        </div>
      )}

      {tab === "search" && (
        <div className="bg-white border rounded-lg p-4">
          {results.length === 0 ? (
            <p className="text-sm text-gray-400">无检索结果。</p>
          ) : (
            <ul className="divide-y">
              {results.map((r, i) => (
                <li key={i} className="py-2 text-sm text-gray-700">
                  <span className="text-xs text-gray-400">{r.episode?.kind}</span> {r.episode?.summary}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === "episodes" && (
        <div className="bg-white border rounded-lg p-4">
          {episodes.length === 0 ? (
            <p className="text-sm text-gray-400">暂无情景记忆。跑一个 job 后这里会记录执行轨迹。</p>
          ) : (
            <ul className="divide-y">
              {episodes.map((e, i) => (
                <li key={e.id ?? i} className="py-2 text-sm text-gray-700">
                  <div className="text-xs text-gray-400">
                    {e.created_at} · {e.kind}
                  </div>
                  {e.summary}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === "facts" && (
        <div className="bg-white border rounded-lg p-4">
          {facts.length === 0 ? (
            <p className="text-sm text-gray-400">暂无事实记忆。</p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {facts.map((f) => (
                  <tr key={f.key} className="border-t">
                    <td className="px-3 py-2 font-medium">{f.key}</td>
                    <td className="px-3 py-2 text-gray-600">{f.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
