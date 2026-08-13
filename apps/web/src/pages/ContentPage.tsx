import { useEffect, useState } from "react";
import { get, post } from "../api";
import type { Content } from "../types";

export default function ContentPage() {
  const [contents, setContents] = useState<Content[]>([]);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  async function load() {
    try {
      setContents(await get<Content[]>("/content"));
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
      await post<Content>("/content", { title, body });
      setTitle("");
      setBody("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">内容创作</h2>
      {error && <p className="text-red-600 text-sm">{error}</p>}

      <form
        className="bg-white rounded-lg shadow p-4 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <input
          className="w-full border rounded px-3 py-2"
          placeholder="内容标题"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          className="w-full border rounded px-3 py-2 min-h-32"
          placeholder="内容正文"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <button
          type="submit"
          className="bg-brand-600 text-white rounded px-4 py-2 hover:bg-brand-700"
        >
          创建内容
        </button>
      </form>

      <ul className="space-y-2">
        {contents.map((c) => (
          <li key={c.id} className="bg-white rounded-lg shadow p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{c.title}</span>
              <span className="text-xs text-gray-500">{c.status}</span>
            </div>
            {c.body && <p className="text-sm text-gray-600 mt-1 line-clamp-2">{c.body}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
