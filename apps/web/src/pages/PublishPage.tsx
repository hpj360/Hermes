import { useEffect, useState } from "react";
import { get, post } from "../api";
import type {
  ComplianceReport,
  Content,
  MetricsSummary,
  PlatformAccount,
  PublishTask,
} from "../types";

export default function PublishPage() {
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [contents, setContents] = useState<Content[]>([]);
  const [tasks, setTasks] = useState<PublishTask[]>([]);
  const [summary, setSummary] = useState<MetricsSummary | null>(null);
  const [error, setError] = useState("");
  const [contentId, setContentId] = useState("");
  const [accountIds, setAccountIds] = useState<string[]>([]);
  const [confirmUrl, setConfirmUrl] = useState<Record<string, string>>({});
  const [compliance, setCompliance] = useState<ComplianceReport | null>(null);
  const [forceCompliance, setForceCompliance] = useState(false);
  const [backfillOpen, setBackfillOpen] = useState<Record<string, boolean>>({});
  const [backfill, setBackfill] = useState<
    Record<string, { views: number; likes: number; comments: number; shares: number; snapshot_date: string }>
  >({});
  const [backfillOk, setBackfillOk] = useState<Record<string, boolean>>({});

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
        force_compliance: forceCompliance,
      });
      setAccountIds([]);
      setCompliance(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function precheckCompliance() {
    const content = contents.find((c) => c.id === contentId);
    if (!content) return;
    try {
      setCompliance(
        await post<ComplianceReport>("/compliance/check", {
          title: content.title,
          body: content.body,
        }),
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function confirmPublish(taskId: string) {
    const url = confirmUrl[taskId]?.trim();
    if (!url) return;
    try {
      await post(`/publish/${taskId}/confirm`, { external_url: url });
      setConfirmUrl((prev) => ({ ...prev, [taskId]: "" }));
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function backfillMetrics(task: { id: string; content_id: string; platform: string }) {
    const form = backfill[task.id];
    if (!form) return;
    try {
      await post("/analytics/manual", {
        content_id: task.content_id,
        platform: task.platform,
        views: form.views || 0,
        likes: form.likes || 0,
        comments: form.comments || 0,
        shares: form.shares || 0,
        snapshot_date: form.snapshot_date,
      });
      setBackfillOk((prev) => ({ ...prev, [task.id]: true }));
      setError("");
    } catch (e) {
      setBackfillOk((prev) => ({ ...prev, [task.id]: false }));
      setError((e as Error).message);
    }
  }

  function updateBackfill(
    taskId: string,
    patch: Partial<{
      views: number;
      likes: number;
      comments: number;
      shares: number;
      snapshot_date: string;
    }>,
  ) {
    setBackfill((prev) => {
      const cur =
        prev[taskId] ??
        {
          views: 0,
          likes: 0,
          comments: 0,
          shares: 0,
          snapshot_date: new Date().toISOString().slice(0, 10),
        };
      return { ...prev, [taskId]: { ...cur, ...patch } };
    });
  }

  function toggleBackfill(t: { id: string }) {
    setBackfillOpen((prev) => ({ ...prev, [t.id]: !prev[t.id] }));
    setBackfill((prev) =>
      prev[t.id]
        ? prev
        : {
            ...prev,
            [t.id]: {
              views: 0,
              likes: 0,
              comments: 0,
              shares: 0,
              snapshot_date: new Date().toISOString().slice(0, 10),
            },
          },
    );
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
        <div className="flex items-center gap-3">
          <button
            onClick={() => void publish()}
            className="bg-brand-600 text-white rounded px-4 py-2 hover:bg-brand-700"
          >
            发布
          </button>
          <button
            onClick={() => void precheckCompliance()}
            className="border border-brand-600 text-brand-600 rounded px-4 py-2 hover:bg-brand-50"
          >
            合规预检
          </button>
          <label className="inline-flex items-center gap-1 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={forceCompliance}
              onChange={(e) => setForceCompliance(e.target.checked)}
            />
            强制发布（跳过红线拦截）
          </label>
        </div>

        {compliance && (
          <div
            className={`rounded p-3 text-sm ${
              compliance.passed
                ? "bg-green-50 text-green-700"
                : "bg-red-50 text-red-700"
            }`}
          >
            <div className="font-medium">{compliance.summary}</div>
            {compliance.blocking.map((h, i) => (
              <div key={i} className="mt-1">
                {h.source === "title" ? "标题" : "正文"}含「{h.keyword}」→{" "}
                {h.rule_name}（{h.rule_id}）
              </div>
            ))}
            {compliance.warnings.map((h, i) => (
              <div key={`w${i}`} className="mt-1 text-amber-600">
                提示：{h.rule_name}「{h.keyword}」
              </div>
            ))}
          </div>
        )}
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
          <li key={t.id} className="bg-white rounded-lg shadow p-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-sm text-gray-500">{t.platform}</span>
                <span className="ml-2 text-xs text-gray-400">{t.status}</span>
                {t.error_message && (
                  <span className="ml-2 text-xs text-amber-600">{t.error_message}</span>
                )}
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
            </div>
            {t.status === "PARTIAL_SUCCESS" && (
              <div className="mt-2 flex gap-2">
                <input
                  className="flex-1 border rounded px-3 py-1 text-sm"
                  placeholder="人工发布后粘贴真实链接"
                  value={confirmUrl[t.id] ?? ""}
                  onChange={(e) =>
                    setConfirmUrl((prev) => ({ ...prev, [t.id]: e.target.value }))
                  }
                />
                <button
                  onClick={() => void confirmPublish(t.id)}
                  className="bg-green-600 text-white rounded px-3 py-1 text-sm hover:bg-green-700"
                >
                  确认发布
                </button>
              </div>
            )}

            <button
              onClick={() => toggleBackfill(t)}
              className="mt-2 text-xs text-gray-500 hover:text-gray-700 hover:underline"
            >
              {backfillOpen[t.id] ? "收起回填" : "📊 人工回填数据（无自动回采的平台）"}
            </button>
            {backfillOpen[t.id] && backfill[t.id] && (
              <div className="mt-2 bg-gray-50 rounded p-3 text-sm">
                <div className="flex flex-wrap gap-2 items-center">
                  {(
                    [
                      ["views", "浏览"],
                      ["likes", "点赞"],
                      ["comments", "评论"],
                      ["shares", "分享"],
                    ] as const
                  ).map(([k, label]) => (
                    <label key={k} className="inline-flex items-center gap-1">
                      {label}
                      <input
                        type="number"
                        min={0}
                        className="w-20 border rounded px-1.5 py-0.5 text-xs"
                        value={backfill[t.id]?.[k] ?? 0}
                        onChange={(e) =>
                          updateBackfill(t.id, { [k]: Number(e.target.value) })
                        }
                      />
                    </label>
                  ))}
                  <input
                    type="date"
                    className="border rounded px-1.5 py-0.5 text-xs"
                    value={backfill[t.id]?.snapshot_date ?? ""}
                    onChange={(e) =>
                      updateBackfill(t.id, { snapshot_date: e.target.value })
                    }
                  />
                  <button
                    onClick={() => void backfillMetrics(t)}
                    className="bg-blue-600 text-white rounded px-3 py-1 text-xs hover:bg-blue-700"
                  >
                    回填
                  </button>
                  {backfillOk[t.id] !== undefined && (
                    <span
                      className={`text-xs ${
                        backfillOk[t.id] ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {backfillOk[t.id]
                        ? "已录入（source=manual）"
                        : "录入失败"}
                    </span>
                  )}
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
