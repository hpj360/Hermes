import { useEffect, useState } from "react";
import { get, patch, post } from "../api";
import type {
  DraftResponse,
  HotNoteListResponse,
  Topic,
  TrendImportResponse,
} from "../types";

const PLATFORMS = ["WECHAT_OFFICIAL", "WECHAT_VIDEO", "DOUYIN", "XIAOHONGSHU", "BILIBILI"];

export default function TopicsPage() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(3);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Record<string, DraftResponse>>({});
  const [draftPlatform, setDraftPlatform] = useState("XIAOHONGSHU");
  const [useLlm, setUseLlm] = useState(false);
  const [hotNotes, setHotNotes] = useState<HotNoteListResponse | null>(null);
  const [hotKeyword, setHotKeyword] = useState("居家调酒");
  const [importResult, setImportResult] = useState<TrendImportResponse | null>(null);

  async function load() {
    try {
      setTopics(await get<Topic[]>("/topics"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create() {
    if (!title.trim()) return;
    try {
      await post<Topic>("/topics", {
        title,
        description,
        priority,
        target_platforms: platforms,
      });
      setTitle("");
      setDescription("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function togglePlatform(p: string) {
    setPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );
  }

  async function scheduleTopic(topicId: string, value: string) {
    try {
      await patch<Topic>(`/topics/${topicId}`, {
        planned_date: value || null,
      });
      await load();
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function saveDraftToContent(topicId: string) {
    const d = drafts[topicId];
    if (!d) return;
    try {
      await post<unknown>(`/topics/${topicId}/content`, {
        title: d.title,
        body: d.body,
      });
      await load();
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function generateDraft(topicId: string) {
    try {
      const draft = await post<DraftResponse>(
        `/topics/${topicId}/draft?platform=${draftPlatform}${useLlm ? "&use_llm=true" : ""}`,
      );
      setDrafts((prev) => ({ ...prev, [topicId]: draft }));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function fetchHotNotes() {
    try {
      const q = hotKeyword.trim()
        ? `&keyword=${encodeURIComponent(hotKeyword.trim())}`
        : "";
      setHotNotes(
        await get<HotNoteListResponse>(
          `/trends/hot-notes?platform=XIAOHONGSHU${q}`,
        ),
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function importTrendTopics() {
    try {
      setImportResult(
        await post<TrendImportResponse>("/trends/import", {
          platform: "XIAOHONGSHU",
          keyword: hotKeyword.trim() || null,
          min_engagement: 500,
          max_fans: 5000,
        }),
      );
      await load();
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">选题池</h2>
      {error && <p className="text-red-600 text-sm">{error}</p>}

      <form
        className="bg-white rounded-lg shadow p-4 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <div className="flex gap-3">
          <input
            className="flex-1 border rounded px-3 py-2"
            placeholder="选题标题"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <select
            className="border rounded px-3 py-2"
            value={priority}
            onChange={(e) => setPriority(Number(e.target.value))}
          >
            {[1, 2, 3, 4, 5].map((p) => (
              <option key={p} value={p}>
                优先级 {p}
              </option>
            ))}
          </select>
        </div>
        <textarea
          className="w-full border rounded px-3 py-2"
          placeholder="选题描述"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          {PLATFORMS.map((p) => (
            <label key={p} className="inline-flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={platforms.includes(p)}
                onChange={() => togglePlatform(p)}
              />
              {p}
            </label>
          ))}
        </div>
        <button
          type="submit"
          className="bg-brand-600 text-white rounded px-4 py-2 hover:bg-brand-700"
        >
          创建选题
        </button>
      </form>

      <div className="bg-white rounded-lg shadow p-4 flex items-center gap-3">
        <span className="text-sm text-gray-600">导入选题库</span>
        <input
          type="file"
          accept=".md"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const reader = new FileReader();
            reader.onload = () => {
              const md = String(reader.result ?? "");
              post<{ imported: number }>("/topics/import", { markdown: md })
                .then(() => load())
                .catch((err) => setError((err as Error).message));
            };
            reader.readAsText(f);
          }}
          className="text-sm"
        />
        <span className="text-sm text-gray-600 ml-4">草稿平台</span>
        <select
          className="border rounded px-2 py-1 text-sm"
          value={draftPlatform}
          onChange={(e) => setDraftPlatform(e.target.value)}
        >
          {PLATFORMS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <label className="inline-flex items-center gap-1 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={useLlm}
            onChange={(e) => setUseLlm(e.target.checked)}
          />
          LLM 创作（未配置自动回退模板）
        </label>
      </div>

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-gray-700">爆款选题雷达</span>
          <input
            className="border rounded px-2 py-1 text-sm w-40"
            placeholder="关键词（可空）"
            value={hotKeyword}
            onChange={(e) => setHotKeyword(e.target.value)}
          />
          <button
            onClick={() => void fetchHotNotes()}
            className="border border-brand-600 text-brand-600 rounded px-3 py-1.5 text-sm hover:bg-brand-50"
          >
            预览爆款
          </button>
          <button
            onClick={() => void importTrendTopics()}
            className="bg-green-600 text-white rounded px-3 py-1.5 text-sm hover:bg-green-700"
          >
            导入选题池
          </button>
        </div>
        {importResult && (
          <p className="text-xs text-gray-500">
            导入 {importResult.imported} 条，跳过重复 {importResult.skipped_duplicates}{" "}
            条（数据源：{importResult.provider}）
          </p>
        )}
        {hotNotes && (
          <div className="space-y-1">
            <p className="text-xs text-gray-400">
              数据源：{hotNotes.provider}
              {hotNotes.provider === "fixture" && "（虚构样例，仅供演示，勿用于运营决策）"}
            </p>
            {hotNotes.notes.map((n, i) => (
              <div
                key={i}
                className="flex items-center justify-between text-sm bg-gray-50 rounded px-2 py-1"
              >
                <span>{n.title}</span>
                <span className="text-xs text-gray-500">
                  互 动{n.engagement}
                  {n.author_fans !== null && ` · 粉丝${n.author_fans}`}
                  {n.author_fans !== null && n.author_fans <= 5000 && " · 低粉"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <ul className="space-y-2">
        {topics.map((t) => (
          <li key={t.id} className="bg-white rounded-lg shadow p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{t.title}</span>
              <span className="text-xs text-gray-500">{t.status}</span>
            </div>
            {t.description && (
              <p className="text-sm text-gray-600 mt-1">{t.description}</p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-400">
              <span>优先级 {t.priority}</span>
              {t.target_platforms.length > 0 && (
                <span>{t.target_platforms.join(", ")}</span>
              )}
              <label className="inline-flex items-center gap-1">
                📅
                <input
                  type="date"
                  className="border rounded px-1.5 py-0.5 text-xs"
                  value={t.planned_date?.slice(0, 10) ?? ""}
                  onChange={(e) => void scheduleTopic(t.id, e.target.value)}
                />
              </label>
            </div>
            {t.keywords.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {t.keywords.map((k) => (
                  <span
                    key={k}
                    className="bg-gray-100 rounded px-1.5 py-0.5 text-xs text-gray-500"
                  >
                    #{k}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-2 flex gap-3">
              <button
                onClick={() => void generateDraft(t.id)}
                className="text-xs text-brand-600 hover:underline"
              >
                生成草稿
              </button>
              {drafts[t.id] && (
                <button
                  onClick={() => void saveDraftToContent(t.id)}
                  className="text-xs text-green-600 hover:underline"
                >
                  存为内容草稿
                </button>
              )}
            </div>
            {drafts[t.id] && (
              <div className="mt-2 bg-gray-50 rounded p-3 text-sm space-y-2">
                <div className="text-xs">
                  <span className="text-gray-500">草稿来源：</span>
                  <span
                    className={`rounded px-1.5 py-0.5 ${
                      drafts[t.id].source === "llm"
                        ? "bg-purple-100 text-purple-700"
                        : "bg-gray-200 text-gray-600"
                    }`}
                  >
                    {drafts[t.id].source === "llm" ? "LLM 生成" : "模板"}
                  </span>
                </div>
                <div>
                  <span className="text-xs text-gray-500">候选标题：</span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {(drafts[t.id].title_candidates_detailed ?? []).map((c) => (
                      <span
                        key={c.title}
                        className="bg-white border rounded px-2 py-0.5 text-xs"
                        title={`${c.mechanism_name}：${c.note}`}
                      >
                        {c.title}
                        <span className="ml-1 text-[10px] text-brand-600">
                          [{c.mechanism_name}]
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="text-xs text-gray-500">正文草稿：</span>
                  <pre className="mt-1 whitespace-pre-wrap text-xs text-gray-700">
                    {drafts[t.id].body}
                  </pre>
                </div>
                <div>
                  <span className="text-xs text-gray-500">标签：</span>
                  <span className="text-xs text-gray-600">
                    {drafts[t.id].hashtags.map((h) => `#${h}`).join(" ")}
                  </span>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
