import { useEffect, useState } from "react";
import { api } from "../api";
import type { CategoryInfo, DocumentItem, TagInfo } from "../types";
import { SkeletonList } from "./Skeleton";

interface DocumentListProps {
  refreshKey: number;
  onChange: () => void;
  onSelectDoc?: (docId: string) => void;
}

/** 文档列表（M2-06：分类+标签筛选）。 */
export function DocumentList({ refreshKey, onChange, onSelectDoc }: DocumentListProps) {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [tags, setTags] = useState<TagInfo[]>([]);
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [filterTagId, setFilterTagId] = useState<number | undefined>(undefined);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [docsResp, catsResp, tagsResp] = await Promise.all([
        api.listDocuments(filterCategory || undefined, filterTagId),
        api.listCategories(),
        api.listTags(),
      ]);
      setDocs(docsResp.items);
      setCategories(catsResp.items);
      setTags(tagsResp.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [refreshKey, filterCategory, filterTagId]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const clearFilters = () => {
    setFilterCategory("");
    setFilterTagId(undefined);
  };

  if (loading && docs.length === 0) {
    return <div className="p-4"><SkeletonList count={4} /></div>;
  }

  if (error) {
    return <div className="p-4 text-center text-red-600">{error}</div>;
  }

  return (
    <div className="flex flex-col h-full">
      {/* 筛选栏 */}
      <div className="flex items-center gap-3 px-4 py-2 border-b bg-gray-50 flex-wrap">
        <span className="text-xs text-gray-500">筛选：</span>
        <select
          className="text-sm border border-gray-300 rounded px-2 py-1 bg-white"
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value)}
        >
          <option value="">全部分类</option>
          {categories.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name} ({c.doc_count})
            </option>
          ))}
        </select>
        <select
          className="text-sm border border-gray-300 rounded px-2 py-1 bg-white"
          value={filterTagId ?? ""}
          onChange={(e) => setFilterTagId(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">全部标签</option>
          {tags.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.doc_count ?? 0})
            </option>
          ))}
        </select>
        {(filterCategory || filterTagId) && (
          <button
            onClick={clearFilters}
            className="text-xs text-gray-500 hover:text-gray-700"
          >
            清除
          </button>
        )}
        <span className="ml-auto text-xs text-gray-500">共 {docs.length} 篇</span>
      </div>

      {/* 列表 */}
      {docs.length === 0 ? (
        <div className="p-8 text-center text-gray-400">
          <div className="text-3xl mb-2">📄</div>
          <p className="text-sm">
            {filterCategory || filterTagId ? "无匹配文档" : "知识库为空"}
          </p>
          <p className="text-xs mt-1">
            {filterCategory || filterTagId
              ? "尝试更换筛选条件"
              : "点击右上角导入或种子知识"}
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500 sticky top-0">
              <tr>
                <th className="text-left px-4 py-2">标题</th>
                <th className="text-left px-3 py-2">分类</th>
                <th className="text-left px-3 py-2">标签</th>
                <th className="text-left px-3 py-2">来源</th>
                <th className="text-right px-3 py-2">分片</th>
                <th className="text-left px-3 py-2">创建时间</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {docs.map((d) => (
                <tr key={d.doc_id} className="hover:bg-gray-50">
                  <td className="px-4 py-2">
                    {onSelectDoc ? (
                      <button
                        onClick={() => onSelectDoc(d.doc_id)}
                        className="text-brand-700 hover:underline text-left"
                      >
                        {d.title}
                      </button>
                    ) : (
                      <span className="text-gray-900">{d.title}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {d.category ? (
                      <span className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-700">
                        {d.category}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(d.tags || []).map((t) => (
                        <span
                          key={t.id}
                          className="text-xs px-1.5 py-0.5 rounded text-white"
                          style={{ backgroundColor: t.color }}
                        >
                          {t.name}
                        </span>
                      ))}
                      {(!d.tags || d.tags.length === 0) && (
                        <span className="text-xs text-gray-400">-</span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-xs px-2 py-0.5 rounded bg-brand-50 text-brand-700">
                      {d.source_type}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right text-gray-600">{d.chunk_count}</td>
                  <td className="px-3 py-2 text-gray-400 text-xs">
                    {d.created_at ? new Date(d.created_at).toLocaleString() : "-"}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {onSelectDoc && (
                      <button
                        onClick={() => onSelectDoc(d.doc_id)}
                        className="text-xs text-brand-700 hover:underline mr-2"
                      >
                        详情
                      </button>
                    )}
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
      )}
    </div>
  );
}
