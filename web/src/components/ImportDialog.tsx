import { useState } from "react";
import { api } from "../api";

interface ImportDialogProps {
  onClose: () => void;
  onImported: () => void;
}

/** 导入对话框：支持纯文本和文件上传。 */
export function ImportDialog({ onClose, onImported }: ImportDialogProps) {
  const [tab, setTab] = useState<"text" | "file">("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileTitle, setFileTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleImportText = async () => {
    if (!title.trim() || !content.trim()) {
      setError("标题和内容不能为空");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.importText(title.trim(), content);
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
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-gray-500"
              }`}
              onClick={() => setTab("text")}
            >
              纯文本
            </button>
            <button
              className={`px-4 py-2 text-sm border-b-2 ${
                tab === "file"
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-gray-500"
              }`}
              onClick={() => setTab("file")}
            >
              文件上传
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
                <label className="text-sm text-gray-700">内容 *</label>
                <textarea
                  className="input mt-1 resize-y"
                  rows={12}
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
          ) : (
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
                <p className="text-xs text-gray-400 mt-1">
                  支持 .txt / .md / .pdf
                </p>
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
          )}
        </div>
      </div>
    </div>
  );
}
