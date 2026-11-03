import { useEffect, useState } from "react";
import { get, post } from "../api";
import type { Content, ValidationResult } from "../types";

export default function ContentPage() {
  const [contents, setContents] = useState<Content[]>([]);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [platform, setPlatform] = useState("XIAOHONGSHU");
  const [checkResult, setCheckResult] = useState<ValidationResult | null>(null);
  const [origResult, setOrigResult] = useState<{
    checked: number;
    max_similarity: number;
    results: {
      ref_type: string;
      ref_id: string;
      ref_title: string;
      similarity: number;
      longest_common_run: string;
    }[];
  } | null>(null);

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
      setCheckResult(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function validate() {
    if (!title.trim()) return;
    try {
      setCheckResult(
        await post<ValidationResult>("/content/validate", {
          title,
          body,
          platform,
        }),
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function checkOriginality() {
    if (!title.trim()) return;
    try {
      setOrigResult(
        await post<{
          checked: number;
          max_similarity: number;
          results: {
            ref_type: string;
            ref_id: string;
            ref_title: string;
            similarity: number;
            longest_common_run: string;
          }[];
        }>("/originality/check", { title, body, min_similarity: 0.3 }),
      );
      setError("");
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
        <div className="flex items-center gap-3">
          <select
            className="border rounded px-2 py-2 text-sm"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
          >
            <option value="XIAOHONGSHU">小红书</option>
            <option value="DOUYIN">抖音</option>
            <option value="WECHAT_OFFICIAL">微信公众号</option>
            <option value="WECHAT_VIDEO">微信视频号</option>
            <option value="BILIBILI">B站</option>
          </select>
          <button
            type="submit"
            className="bg-brand-600 text-white rounded px-4 py-2 hover:bg-brand-700"
          >
            创建内容
          </button>
          <button
            type="button"
            onClick={() => void validate()}
            className="border border-brand-600 text-brand-600 rounded px-4 py-2 hover:bg-brand-50"
          >
            发布前校验
          </button>
          <button
            type="button"
            onClick={() => void checkOriginality()}
            className="border border-gray-400 text-gray-600 rounded px-4 py-2 hover:bg-gray-50"
          >
            原创性查重
          </button>
        </div>
        {origResult && (
          <div
            className={`rounded p-3 text-sm ${
              origResult.results.length === 0
                ? "bg-green-50 text-green-700"
                : "bg-amber-50 text-amber-800"
            }`}
          >
            <div className="font-medium">
              原创性查重：比对 {origResult.checked} 条参考，
              {origResult.results.length === 0
                ? "未发现高度相似内容"
                : `最高相似度 ${Math.round(origResult.max_similarity * 100)}%`}
            </div>
            {origResult.results.slice(0, 5).map((r, i) => (
              <div key={i} className="mt-1 text-xs">
                [{r.ref_type === "content" ? "已存内容" : "选题库"}]{" "}
                {r.ref_title} · 相似度{" "}
                {(r.similarity * 100).toFixed(1)}%
                {r.longest_common_run.length >= 15 && " · 连续15字以上雷同"}
                {r.longest_common_run.length > 0 &&
                  ` · 片段「${r.longest_common_run.slice(0, 24)}…」`}
              </div>
            ))}
            <div className="mt-1 text-[10px] text-gray-400">
              字面查重覆盖语义/图片盲区之外，发布前仍需人工原创性三查
            </div>
          </div>
        )}
        {checkResult && (
          <div
            className={`rounded p-3 text-sm space-y-1 ${
              checkResult.passed
                ? "bg-green-50 text-green-700"
                : "bg-red-50 text-red-700"
            }`}
          >
            <div className="font-medium">
              {checkResult.passed ? "校验通过" : "校验未通过"}
            </div>
            {checkResult.blocking.map((b, i) => (
              <div key={`b${i}`}>🚫 {b}</div>
            ))}
            {checkResult.platform_errors.map((e, i) => (
              <div key={`p${i}`}>📏 {e}</div>
            ))}
            {checkResult.sop_warnings.map((w, i) => (
              <div key={`w${i}`} className="text-amber-600">
                ⚠️ {w}
              </div>
            ))}
            {Object.keys(checkResult.keyword_coverage).length > 0 && (
              <div className="text-xs">
                关键词覆盖：
                {Object.entries(checkResult.keyword_coverage).map(
                  ([k, v]) => (
                    <span
                      key={k}
                      className={`ml-1 ${v ? "text-green-600" : "text-red-500"}`}
                    >
                      {v ? "✓" : "✗"}#{k}
                    </span>
                  ),
                )}
              </div>
            )}
          </div>
        )}
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
