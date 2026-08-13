import { useEffect, useState } from "react";
import { get, post } from "../api";
import type { Content, MetricsSummary, PlatformAccount, PublishTask } from "../types";

export default function PublishPage() {
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [contents, setContents] = useState<Content[]>([]);
  const [tasks, setTasks] = useState<PublishTask[]>([]);
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [error, setError] = useState("");
  const [contentId, setContentId] = useState("");
  const [accountIds, setAccountIds] = useState<string[]>([]);

  async function load() {
    try {
      const [a, c, t] = await Promise.all([
        get<PlatformAccount[]>("/accounts"),
        get<Content[]>("/content"),
        get<PublishTask[]>("/publish"),
      ]);
      setAccounts(a);
      setContents(c);
      setTasks(t);
      try {
        setSummary(await get<MetricsSummary>("/analytics/summary"));
      } catch {
        setSummary(null);
      }
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function publish() {
    if (!contentId || accountIds.length === 0) return;
    try {
      await post("/publish", {
        content_id: contentId,
        platform_account_ids: accountIds,
      });
      setAccountIds([]);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function toggleAccount(id: string) {
    setAccountIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">发布管理</h2>
      {error && <p className="text-red-600 text-sm">{error}</p>}

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <select
          className="w-full border rounded px-3 py-2"
          value={contentId}
          onChange={(e) => setContentId(e.target.value)}
        >
          <option value="">选择要发布的内容…</option>
          {contents.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <div className="flex flex-wrap gap-2">
          {accounts.map((a) => (
            <label key={a.id} className="inline-flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={accountIds.includes(a.id)}
                onChange={() => toggleAccount(a.id)}
              />
              {a.display_name}（{a.platform}）
            </label>
          ))}
        </div>
        <button
          onClick={() => void publish()}
          className="bg-brand-600 text-white rounded px-4 py-2 hover:bg-brand-700"
        >
          发布
        </button>
      </div>

      {summary && (
        <div className="bg-white rounded-lg shadow p-4 grid grid-cols-3 gap-4 text-sm">
          <div>总浏览：{summary.total_views}</div>
          <div>总点赞：{summary.total_likes}</div>
          <div>平均互动率：{(summary.avg_engagement_rate * 100).toFixed(2)}%</div>
        </div>
      )}

      <ul className="space-y-2">
        {tasks.map((t) => (
          <li key={t.id} className="bg-white rounded-lg shadow p-4 flex items-center justify-between">
            <div>
              <span className="text-sm text-gray-500">{t.platform}</span>
              <span className="ml-2 text-xs text-gray-400">{t.status}</span>
            </div>
            {t.external_url && (
              <a
                className="text-brand-600 text-sm hover:underline"
                href={t.external_url}
                target="_blank"
                rel="noreferrer"
              >
                查看
              </a>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
