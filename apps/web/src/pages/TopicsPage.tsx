import { useEffect, useState } from "react";
import { get, post } from "../api";
import type { Topic } from "../types";

const PLATFORMS = ["WECHAT_OFFICIAL", "WECHAT_VIDEO", "DOUYIN", "XIAOHONGSHU", "BILIBILI"];

export default function TopicsPage() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(3);
  const [platforms, setPlatforms] = useState<string[]>([]);

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
            <div className="mt-2 flex gap-2 text-xs text-gray-400">
              <span>优先级 {t.priority}</span>
              {t.target_platforms.length > 0 && (
                <span>{t.target_platforms.join(", ")}</span>
              )}
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
          </li>
        ))}
      </ul>
    </div>
  );
}
