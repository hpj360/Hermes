import { useEffect, useState } from "react";
import { api } from "../api";
import type { LabRecipe } from "../types";

interface PendingReviewPanelProps {
  /** 外部传入的刷新信号：每次自增触发重新加载。 */
  refreshTick?: number;
  /** 审核结果回调（通过/驳回后通知父组件刷新列表）。 */
  onResolved?: () => void;
}

/** M4.3 待审核队列：列出 status=pending 的配方，支持通过/驳回。 */
export function PendingReviewPanel({ refreshTick, onResolved }: PendingReviewPanelProps) {
  const [items, setItems] = useState<LabRecipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyDocId, setBusyDocId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await api.labRecipes({ status: "pending", limit: 100 });
      setItems(resp.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [refreshTick]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleApprove = async (docId: string) => {
    setBusyDocId(docId);
    try {
      await api.labApproveRecipe(docId);
      await load();
      onResolved?.();
    } catch (err) {
      alert(`通过失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setBusyDocId(null);
    }
  };

  const handleReject = async (docId: string) => {
    // 浏览器原生 prompt 与 mockup recipe-editor 行为一致；测试环境 jsdom 可 stubGlobal prompt。
    const reason = typeof window !== "undefined" && typeof window.prompt === "function"
      ? window.prompt("驳回理由：") || ""
      : "";
    setBusyDocId(docId);
    try {
      await api.labRejectRecipe(docId, reason);
      await load();
      onResolved?.();
    } catch (err) {
      alert(`驳回失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setBusyDocId(null);
    }
  };

  return (
    <div className="card p-4 mb-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-base font-semibold text-ink-900">📨 待审核配方</h3>
        <span className="text-xs text-gray-400">
          {loading ? "加载中…" : items.length > 0 ? `共 ${items.length} 条 UGC 投稿待审` : "当前无 UGC 投稿待审"}
        </span>
      </div>

      {error && (
        <div className="text-sm text-red-600 py-2">加载失败：{error}</div>
      )}

      {!loading && items.length === 0 && !error && (
        <div className="text-sm text-gray-400 py-4 text-center">暂无待审核配方</div>
      )}

      {items.length > 0 && (
        <ul className="divide-y divide-ink-100">
          {items.map((r) => (
            <li
              key={r.doc_id}
              className="py-2 flex items-center justify-between gap-3"
              data-doc-id={r.doc_id}
            >
              <div className="min-w-0 flex-1">
                <div className="font-medium text-sm text-ink-900 truncate">
                  {r.title || "(未命名)"}
                </div>
                <div className="text-xs text-gray-400 truncate">
                  {r.doc_id}
                  {r.source ? ` · ${r.source}` : ""}
                </div>
              </div>
              <div className="flex gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => handleApprove(r.doc_id)}
                  disabled={busyDocId === r.doc_id}
                  className="text-xs px-3 py-1 rounded bg-brand-700 text-white hover:opacity-90 disabled:opacity-50"
                >
                  通过
                </button>
                <button
                  type="button"
                  onClick={() => handleReject(r.doc_id)}
                  disabled={busyDocId === r.doc_id}
                  className="text-xs px-3 py-1 rounded border border-red-500 text-red-500 hover:bg-red-500 hover:text-white disabled:opacity-50"
                >
                  驳回
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
