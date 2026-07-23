import { useState } from "react";
import { api } from "../api";
import type { BatchImportResult } from "../types";

interface ImportDialogProps {
  onClose: () => void;
  onImported: () => void;
}

/** 导入对话框：纯文本 / 单文件 / 批量上传（M2-05）。 */
export function ImportDialog({ onClose, onImported }: ImportDialogProps) {
  const [tab, setTab] = useState<"text" | "file" | "batch">("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileTitle, setFileTitle] = useState("");
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [batchResult, setBatchResult] = useState<BatchImportResult | null>(null);

  const handleImportText = async () => {
    if (!title.trim() || !content.trim()) {
      setError("标题和内容不能为空");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.importText(title.trim(), content, category.trim() || undefined);
      onImported();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError("请选择文件");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.uploadFile(file, fileTitle.trim() || undefined);
      onImported();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setLoading(false);
    }
  };

  const handleBatchUpload = async () => {
    if (batchFiles.length === 0) {
      setError("请至少选择 1 个文件");
      return;
    }
    if (batchFiles.length > 20) {
      setError(`单次最多 20 个文件，当前 ${batchFiles.length} 个`);
      return;
    }
    setLoading(true);
    setError("");
    setBatchResult(null);
    try {
      const result = await api.uploadBatch(batchFiles);
      setBatchResult(result);
      if (result.imported > 0) {
        onImported();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量上传失败");
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    const valid = files.filter((f) => /\.(txt|md|pdf)$/i.test(f.name));
    if (valid.length === 0) {
      setError("仅支持 .txt / .md / .pdf 文件");
      return;
    }
    setBatchFiles((prev) => [...prev, ...valid].slice(0, 20));
    setError("");
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setBatchFiles((prev) => [...prev, ...files].slice(0, 20));
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40">
      <div className="card max-w-2xl w-full mx-4 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h3 className="font-semibold text-gray-900">导入文档</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="px-6 pt-4">
          <div className="flex gap-1 border-b">
            <button
              className={`px-4 py-2 text-sm border-b-2 ${
                tab === "text"
                  ? "border-brand-700 text-brand-700"
                  : "border-transparent text-gray-500"
              }`}
              onClick={() => setTab("text")}
            >
              纯文本
            </button>
            <button
              className={`px-4 py-2 text-sm border-b-2 ${
                tab === "file"
                  ? "border-brand-700 text-brand-700"
                  : "border-transparent text-gray-500"
              }`}
              onClick={() => setTab("file")}
            >
              单文件
            </button>
            <button
              className={`px-4 py-2 text-sm border-b-2 ${
                tab === "batch"
                  ? "border-brand-700 text-brand-700"
                  : "border-transparent text-gray-500"
              }`}
              onClick={() => setTab("batch")}
            >
              批量上传 (≤20)
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {error && (
            <div className="mb-3 text-sm text-red-700 bg-red-50 rounded px-3 py-2">
              {error}
            </div>
          )}

          {tab === "text" ? (
            <div className="space-y-3">
              <div>
                <label className="text-sm text-gray-700">标题 *</label>
                <input
                  className="input mt-1"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="文档标题"
                  disabled={loading}
                />
              </div>
              <div>
                <label className="text-sm text-gray-700">分类（可选）</label>
                <input
                  className="input mt-1"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="如：烈酒 / 葡萄酒 / 中国白酒"
                  disabled={loading}
                />
              </div>
              <div>
                <label className="text-sm text-gray-700">内容 *</label>
                <textarea
                  className="input mt-1 resize-y"
                  rows={10}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="粘贴文档内容..."
                  disabled={loading}
                />
                <p className="text-xs text-gray-400 mt-1">
                  支持 Markdown 语法，将自动分片（500 字符/片，80 字符重叠）
                </p>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button onClick={onClose} className="btn-secondary" disabled={loading}>
                  取消
                </button>
                <button
                  onClick={handleImportText}
                  className="btn-primary"
                  disabled={loading}
                >
                  {loading ? "导入中..." : "导入"}
                </button>
              </div>
            </div>
          ) : tab === "file" ? (
            <div className="space-y-3">
              <div>
                <label className="text-sm text-gray-700">文件 *</label>
                <input
                  type="file"
                  accept=".txt,.md,.pdf"
                  className="mt-1 block w-full text-sm"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  disabled={loading}
                />
                <p className="text-xs text-gray-400 mt-1">支持 .txt / .md / .pdf</p>
              </div>
              <div>
                <label className="text-sm text-gray-700">标题（可选）</label>
                <input
                  className="input mt-1"
                  value={fileTitle}
                  onChange={(e) => setFileTitle(e.target.value)}
                  placeholder="留空使用文件名"
                  disabled={loading}
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button onClick={onClose} className="btn-secondary" disabled={loading}>
                  取消
                </button>
                <button
                  onClick={handleUpload}
                  className="btn-primary"
                  disabled={loading || !file}
                >
                  {loading ? "上传中..." : "上传"}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {/* 拖拽区 */}
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                className={`border-2 border-dashed rounded p-6 text-center transition-colors ${
                  dragOver ? "border-brand-500 bg-brand-50" : "border-gray-300"
                }`}
              >
                <div className="text-3xl mb-2">📁</div>
                <p className="text-sm text-gray-600">拖拽文件到此处</p>
                <p className="text-xs text-gray-400 my-1">或</p>
                <label className="btn-secondary text-sm cursor-pointer">
                  选择文件
                  <input
                    type="file"
                    multiple
                    accept=".txt,.md,.pdf"
                    className="hidden"
                    onChange={handleFileInput}
                    disabled={loading}
                  />
                </label>
                <p className="text-xs text-gray-400 mt-2">
                  支持 .txt / .md / .pdf，单次最多 20 个
                </p>
              </div>

              {/* 已选文件列表 */}
              {batchFiles.length > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-500">
                      已选 {batchFiles.length} 个文件
                    </span>
                    <button
                      onClick={() => setBatchFiles([])}
                      className="text-xs text-gray-500 hover:text-red-500"
                      disabled={loading}
                    >
                      清空
                    </button>
                  </div>
                  <ul className="max-h-40 overflow-y-auto border rounded divide-y">
                    {batchFiles.map((f, i) => (
                      <li
                        key={`${f.name}-${i}`}
                        className="flex items-center justify-between px-2 py-1 text-xs"
                      >
                        <span className="truncate">{f.name}</span>
                        <span className="text-gray-400 ml-2">
                          {(f.size / 1024).toFixed(1)} KB
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* 批量结果 */}
              {batchResult && (
                <div className="border rounded p-3 bg-gray-50 text-sm">
                  <div className="font-medium mb-2">
                    导入完成：{batchResult.imported}/{batchResult.total} 成功
                    {batchResult.failed > 0 && (
                      <span className="text-red-600">（{batchResult.failed} 失败）</span>
                    )}
                  </div>
                  <ul className="space-y-1 max-h-40 overflow-y-auto">
                    {batchResult.results.map((r, i) => (
                      <li
                        key={i}
                        className={`text-xs ${
                          r.status === "imported" ? "text-green-700" : "text-red-700"
                        }`}
                      >
                        {r.status === "imported" ? "✓" : "✗"} {r.filename}
                        {r.error && ` - ${r.error}`}
                        {r.chunk_count !== undefined && ` (${r.chunk_count} 分片)`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button onClick={onClose} className="btn-secondary" disabled={loading}>
                  关闭
                </button>
                <button
                  onClick={handleBatchUpload}
                  className="btn-primary"
                  disabled={loading || batchFiles.length === 0}
                >
                  {loading ? `上传中...` : `上传 ${batchFiles.length} 个文件`}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
