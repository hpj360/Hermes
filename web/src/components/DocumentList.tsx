import { useEffect, useState } from "react";
import { api } from "../api";
import type { DocumentItem } from "../types";

interface DocumentListProps {
  refreshKey: number;
  onChange: () => void;
}

/** 文档列表（管理：删除）。 */
export function DocumentList({ refreshKey, onChange }: DocumentListProps) {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.listDocuments();
      setDocs(r.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = async (docId: string, title: string) => {
    if (!confirm(`确认删除文档「${title}」？此操作不可恢复。`)) return;
    try {
      await api.deleteDocument(docId);
      await load();
      onChange();
    } catch (err) {
      alert(`删除失败：${err instanceof Error ? err.message : err}`);
    }
  };

  if (loading && docs.length === 0) {
    return <div className="p-4 text-center text-gray-400">加载中...</div>;
  }

  if (error) {
    return <div className="p-4 text-center text-red-600">{error}</div>;
  }

  if (docs.length === 0) {
    return (
      <div className="p-8 text-center text-gray-400">
        <div className="text-3xl mb-2">📄</div>
        <p className="text-sm">知识库为空</p>
        <p className="text-xs mt-1">点击右上角"导入"添加文档，或先导入种子知识</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-xs uppercase text-gray-500 sticky top-0">
          <tr>
            <th className="text-left px-4 py-2">标题</th>
            <th className="text-left px-3 py-2">类型</th>
            <th className="text-left px-3 py-2">来源</th>
            <th className="text-right px-3 py-2">分片数</th>
            <th className="text-left px-3 py-2">创建时间</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {docs.map((d) => (
            <tr key={d.doc_id} className="hover:bg-gray-50">
              <td className="px-4 py-2 text-gray-900">{d.title}</td>
              <td className="px-3 py-2 text-gray-500 uppercase text-xs">{d.file_type}</td>
              <td className="px-3 py-2">
                <span className="text-xs px-2 py-0.5 rounded bg-brand-50 text-brand-700">
                  {d.source_type}
                </span>
              </td>
              <td className="px-3 py-2 text-right text-gray-600">{d.chunk_count}</td>
              <td className="px-3 py-2 text-gray-400 text-xs">
                {d.created_at ? new Date(d.created_at).toLocaleString() : "-"}
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  onClick={() => handleDelete(d.doc_id, d.title)}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
