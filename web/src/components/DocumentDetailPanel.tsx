import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { DocumentDetail, TagInfo } from "../types";
import { Skeleton, SkeletonText } from "./Skeleton";

interface DocumentDetailPanelProps {
  docId: string;
  highlightChunk?: number;
  onBack: () => void;
  onChange: () => void;
}

/** M2-03 文档详情面板：左侧目录 + 右侧全文 + chunk 高亮。 */
export function DocumentDetailPanel({
  docId,
  highlightChunk,
  onBack,
  onChange,
}: DocumentDetailPanelProps) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editTagIds, setEditTagIds] = useState<number[]>([]);
  const [allTags, setAllTags] = useState<TagInfo[]>([]);
  const [saving, setSaving] = useState(false);
  const chunkRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const d = await api.getDocument(docId);
      setDetail(d);
      setEditTitle(d.doc.title);
      setEditCategory(d.doc.category);
      setEditTagIds(d.tags.map((t) => t.id).filter(Boolean) as number[]);
      const tagsResp = await api.listTags();
      setAllTags(tagsResp.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [docId]); // eslint-disable-line react-hooks/exhaustive-deps

  // M2-04：高亮 chunk 自动滚动
  useEffect(() => {
    if (!detail || highlightChunk === undefined) return;
    const t = setTimeout(() => {
      const el = chunkRefs.current[highlightChunk];
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-4", "ring-brand-200", "bg-brand-50");
        setTimeout(() => {
          el.classList.remove("ring-4", "ring-brand-200", "bg-brand-50");
        }, 2000);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [detail, highlightChunk]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateDocMetadata(docId, {
        title: editTitle,
        category: editCategory,
        tag_ids: editTagIds,
      });
      setEditing(false);
      await load();
      onChange();
    } catch (err) {
      alert(`保存失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDownload = async () => {
    try {
      await api.downloadDocumentRaw(docId);
    } catch (err) {
      alert(`下载失败：${err instanceof Error ? err.message : err}`);
    }
  };

  if (loading) {
    return (
      <div className="p-8 max-w-3xl mx-auto">
        <Skeleton height="1.75rem" width="50%" className="mb-6" />
        <SkeletonText lines={8} lastLineRatio={0.7} />
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-8 text-center">
        <p className="text-red-600 mb-3">{error}</p>
        <button onClick={onBack} className="btn-secondary">返回</button>
      </div>
    );
  }
  if (!detail) return null;

  const { doc, chunks } = detail;

  return (
    <div className="flex flex-col h-full">
      {/* 顶部工具栏 */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-gray-50">
        <button onClick={onBack} className="text-sm text-gray-600 hover:text-gray-900">
          ← 返回列表
        </button>
        <div className="flex gap-2">
          <button onClick={handleDownload} className="btn-secondary text-sm">
            下载
          </button>
          <button
            onClick={() => setEditing(!editing)}
            className="btn-secondary text-sm"
          >
            {editing ? "取消" : "编辑"}
          </button>
        </div>
      </div>

      {/* 编辑区 */}
      {editing && (
        <div className="px-4 py-3 bg-yellow-50 border-b space-y-2">
          <div>
            <label className="text-xs text-gray-600">标题</label>
            <input
              className="input mt-1"
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              disabled={saving}
            />
          </div>
          <div>
            <label className="text-xs text-gray-600">分类</label>
            <input
              className="input mt-1"
              value={editCategory}
              onChange={(e) => setEditCategory(e.target.value)}
              placeholder="如：烈酒 / 葡萄酒 / 中国白酒"
              disabled={saving}
            />
          </div>
          <div>
            <label className="text-xs text-gray-600">标签（多选）</label>
            <div className="flex flex-wrap gap-2 mt-1">
              {allTags.length === 0 && (
                <span className="text-xs text-gray-400">暂无标签，请先在标签管理创建</span>
              )}
              {allTags.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    if (editTagIds.includes(t.id)) {
                      setEditTagIds(editTagIds.filter((x) => x !== t.id));
                    } else {
                      setEditTagIds([...editTagIds, t.id]);
                    }
                  }}
                  className={`text-xs px-2 py-1 rounded border transition-colors ${
                    editTagIds.includes(t.id)
                      ? "bg-brand-700 text-white border-brand-700"
                      : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                  }`}
                  style={!editTagIds.includes(t.id) ? { borderColor: t.color } : {}}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={handleSave}
            className="btn-primary text-sm"
            disabled={saving || !editTitle.trim()}
          >
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      )}

      {/* 主体：左目录 + 右全文 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：元信息 + chunk 目录 */}
        <aside className="w-64 border-r bg-gray-50 overflow-y-auto p-4 flex-shrink-0">
          <h2 className="font-bold text-gray-900 mb-2 break-all">{doc.title}</h2>
          <dl className="text-xs space-y-1 text-gray-600">
            <div><dt className="inline font-medium">类型：</dt><dd className="inline">{doc.file_type.toUpperCase()}</dd></div>
            <div><dt className="inline font-medium">来源：</dt><dd className="inline">{doc.source_type}</dd></div>
            <div><dt className="inline font-medium">分类：</dt><dd className="inline">{doc.category || "未分类"}</dd></div>
            <div><dt className="inline font-medium">分片：</dt><dd className="inline">{doc.chunk_count}</dd></div>
            <div><dt className="inline font-medium">字符：</dt><dd className="inline">{doc.content_length}</dd></div>
            <div><dt className="inline font-medium">创建：</dt><dd className="inline">{doc.created_at ? new Date(doc.created_at).toLocaleString() : "-"}</dd></div>
          </dl>
          {detail.tags.length > 0 && (
            <div className="mt-3">
              <div className="text-xs font-medium text-gray-500 mb-1">标签</div>
              <div className="flex flex-wrap gap-1">
                {detail.tags.map((t) => (
                  <span
                    key={t.id}
                    className="text-xs px-2 py-0.5 rounded text-white"
                    style={{ backgroundColor: t.color }}
                  >
                    {t.name}
                  </span>
                ))}
              </div>
            </div>
          )}
          {chunks.length > 0 && (
            <div className="mt-4">
              <div className="text-xs font-medium text-gray-500 mb-1">分片目录</div>
              <ol className="space-y-1">
                {chunks.map((c) => (
                  <li key={c.rowid}>
                    <a
                      href={`#chunk-${c.rowid}`}
                      onClick={(e) => {
                        e.preventDefault();
                        const el = chunkRefs.current[c.rowid];
                        el?.scrollIntoView({ behavior: "smooth", block: "center" });
                      }}
                      className="block text-xs text-brand-700 hover:underline truncate"
                      title={c.text.slice(0, 60)}
                    >
                      #{c.idx + 1} {c.text.slice(0, 30)}...
                    </a>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </aside>

        {/* 右侧：全文（按 chunk 渲染，带 rowid 锚点） */}
        <main className="flex-1 overflow-y-auto p-6">
          {chunks.length === 0 ? (
            <div className="text-center text-gray-400 mt-12">
              此文档无分片内容（可能为空文档）
            </div>
          ) : (
            <div className="space-y-4 max-w-3xl">
              {chunks.map((c) => (
                <div
                  key={c.rowid}
                  id={`chunk-${c.rowid}`}
                  ref={(el) => {
                    chunkRefs.current[c.rowid] = el;
                  }}
                  className="border border-gray-200 rounded p-4 transition-all duration-300"
                >
                  <div className="text-xs text-gray-400 mb-2 flex items-center justify-between">
                    <span>分片 #{c.idx + 1} · rowid={c.rowid}</span>
                    <span>chars {c.char_start}-{c.char_end}</span>
                  </div>
                  <div className="text-gray-800 whitespace-pre-wrap leading-relaxed">
                    {c.text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
