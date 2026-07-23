import { useEffect, useState } from "react";
import { api } from "./api";
import type { HealthStatus } from "./types";
import { AgeGate } from "./components/AgeGate";
import { Login } from "./components/Login";
import { ChatPanel } from "./components/ChatPanel";
import { DocumentList } from "./components/DocumentList";
import { DocumentDetailPanel } from "./components/DocumentDetailPanel";
import { ImportDialog } from "./components/ImportDialog";
import { TagPanel } from "./components/TagPanel";
import { LabPanel } from "./components/LabPanel";
import { RecipePanel } from "./components/RecipePanel";
import { RecipeEditorPanel } from "./components/RecipeEditorPanel";
import { Skeleton } from "./components/Skeleton";

type Tab = "chat" | "docs" | "detail" | "tags" | "lab" | "recipes" | "recipe-editor";

export default function App() {
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [needLogin, setNeedLogin] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");
  const [showImport, setShowImport] = useState(false);
  const [docRefreshKey, setDocRefreshKey] = useState(0);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // M2-04：跨页面跳转
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [highlightChunk, setHighlightChunk] = useState<number | undefined>(undefined);
  const [seeding, setSeeding] = useState(false);
  // M4 实验室 / 配方治理
  const [editingRecipeId, setEditingRecipeId] = useState<string | undefined>(undefined);

  // 健康检查（同时判断是否需要登录）
  const refreshHealth = async () => {
    try {
      const h = await api.health();
      setHealth(h);
      if (h.auth_enabled && !api.getToken()) {
        setNeedLogin(true);
      } else {
        setNeedLogin(false);
      }
      setAuthReady(true);
    } catch {
      setAuthReady(true);
    }
  };

  useEffect(() => {
    if (ageConfirmed) refreshHealth();
  }, [ageConfirmed]); // eslint-disable-line react-hooks/exhaustive-deps

  // 年龄门未确认
  if (!ageConfirmed) {
    return <AgeGate onConfirm={() => setAgeConfirmed(true)} />;
  }

  // 等待健康检查
  if (!authReady) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4" style={{ background: "var(--paper-bg)" }}>
        <div className="text-3xl reveal-item">🍷</div>
        <div className="w-48 reveal-item delay-2">
          <Skeleton height="0.875rem" width="100%" className="mb-2" />
          <Skeleton height="0.875rem" width="60%" />
        </div>
      </div>
    );
  }

  // 需要登录
  if (needLogin) {
    return <Login onLogin={() => { setNeedLogin(false); refreshHealth(); }} />;
  }

  const refreshDocs = () => {
    setDocRefreshKey((k) => k + 1);
    refreshHealth();
  };

  // M2-04：从问答引用跳转到文档详情
  const jumpToDocChunk = (docId: string, chunkRowid?: number) => {
    setSelectedDocId(docId);
    setHighlightChunk(chunkRowid);
    setTab("detail");
    setSidebarOpen(false);
  };

  const handleSelectDoc = (docId: string) => {
    setSelectedDocId(docId);
    setHighlightChunk(undefined);
    setTab("detail");
  };

  const handleBackToList = () => {
    setSelectedDocId(null);
    setHighlightChunk(undefined);
    setTab("docs");
  };

  const handleSeed = async () => {
    if (!confirm("将导入 5 篇酒类种子知识（金酒/威士忌/葡萄酒/白酒/朗姆+龙舌兰），是否继续？")) return;
    setSeeding(true);
    try {
      const result = await api.seed();
      alert(`导入完成：${result.seeded} 篇成功${result.failed > 0 ? `，${result.failed} 篇失败` : ""}`);
      refreshDocs();
    } catch (err) {
      alert(`导入失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div className="h-screen flex flex-col relative bg-noise" style={{ background: "var(--paper-bg)" }}>
      {/* 顶部栏 — F6: 深酒红渐变 + 金箔标题，营造高级酒类杂志感 */}
      <header
        className="bg-brand-gradient px-4 py-3 flex items-center justify-between flex-shrink-0 relative overflow-hidden"
        style={{ boxShadow: "var(--shadow-md)" }}
      >
        <div className="flex items-center gap-3 relative z-10">
          <div className="text-2xl">🍷</div>
          <div>
            <h1 className="font-bold text-gold-foil" style={{ fontFamily: "var(--font-serif)" }}>Hermes 知识库</h1>
            {health && (
              <p className="text-xs" style={{ color: "rgba(250, 243, 220, 0.75)" }}>
                {health.doc_count} 篇文档 ·{" "}
                <span style={{ color: health.llm_available ? "#B8E6C9" : "#F5D49A" }}>
                  LLM: {health.llm_provider}{health.llm_available ? "" : "（mock）"}
                </span>{" "}
                ·{" "}
                <span style={{ color: health.embedding_available ? "#B8E6C9" : "#F5D49A" }}>
                  Embed: {health.embedding_provider}{health.embedding_available ? "" : "（hash）"}
                </span>
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {health && health.doc_count === 0 && (
            <button
              onClick={handleSeed}
              className="btn-secondary text-sm"
              disabled={seeding}
            >
              {seeding ? "导入中..." : "导入种子知识"}
            </button>
          )}
          <button
            onClick={() => setShowImport(true)}
            className="btn-primary text-sm"
          >
            导入
          </button>
          {health?.auth_enabled && (
            <button
              onClick={() => {
                api.logout();
                setNeedLogin(true);
              }}
              className="btn-secondary text-sm"
            >
              退出
            </button>
          )}
        </div>
      </header>

      {/* 主体 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 侧边导航（响应式） */}
        <nav
          className={`${
            sidebarOpen ? "block" : "hidden"
          } md:block w-48 bg-white border-r flex-shrink-0 reveal-stagger`}
        >
          <button
            className={`w-full text-left px-4 py-3 text-sm border-b ${
              tab === "chat"
                ? "bg-brand-50 text-brand-700 font-medium"
                : "text-gray-700 hover:bg-gray-50"
            }`}
            onClick={() => { setTab("chat"); setSidebarOpen(false); }}
          >
            💬 问答
          </button>
          <button
            className={`w-full text-left px-4 py-3 text-sm border-b ${
              tab === "docs"
                ? "bg-brand-50 text-brand-700 font-medium"
                : "text-gray-700 hover:bg-gray-50"
            }`}
            onClick={() => { setTab("docs"); setSidebarOpen(false); }}
          >
            📄 文档管理
          </button>
          <button
            className={`w-full text-left px-4 py-3 text-sm border-b ${
              tab === "tags"
                ? "bg-brand-50 text-brand-700 font-medium"
                : "text-gray-700 hover:bg-gray-50"
            }`}
            onClick={() => { setTab("tags"); setSidebarOpen(false); }}
          >
            🏷️ 标签管理
          </button>
          <button
            className={`w-full text-left px-4 py-3 text-sm border-b ${
              tab === "lab"
                ? "bg-brand-50 text-brand-700 font-medium"
                : "text-gray-700 hover:bg-gray-50"
            }`}
            onClick={() => { setTab("lab"); setSidebarOpen(false); }}
          >
            🧪 实验室
          </button>
          <button
            className={`w-full text-left px-4 py-3 text-sm border-b ${
              tab === "recipes" || tab === "recipe-editor"
                ? "bg-brand-50 text-brand-700 font-medium"
                : "text-gray-700 hover:bg-gray-50"
            }`}
            onClick={() => { setTab("recipes"); setEditingRecipeId(undefined); setSidebarOpen(false); }}
          >
            📝 配方
          </button>
        </nav>

        {/* 内容区 */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {/* 移动端切换按钮 */}
          <button
            className="md:hidden px-4 py-2 text-sm bg-gray-100 border-b"
            onClick={() => setSidebarOpen((o) => !o)}
          >
            切换面板
          </button>
          {tab === "chat" ? (
            <ChatPanel refreshDocs={refreshDocs} onJumpToDoc={jumpToDocChunk} />
          ) : tab === "docs" ? (
            <DocumentList
              refreshKey={docRefreshKey}
              onChange={refreshHealth}
              onSelectDoc={handleSelectDoc}
            />
          ) : tab === "detail" && selectedDocId ? (
            <DocumentDetailPanel
              docId={selectedDocId}
              highlightChunk={highlightChunk}
              onBack={handleBackToList}
              onChange={refreshDocs}
            />
          ) : tab === "tags" ? (
            <TagPanel onChange={refreshDocs} />
          ) : tab === "lab" ? (
            <LabPanel onJumpToDoc={jumpToDocChunk} />
          ) : tab === "recipe-editor" ? (
            <RecipeEditorPanel
              docId={editingRecipeId}
              onSaved={() => { setTab("recipes"); setEditingRecipeId(undefined); }}
              onCancel={() => { setTab("recipes"); setEditingRecipeId(undefined); }}
            />
          ) : tab === "recipes" ? (
            <RecipePanel
              onCreateRecipe={() => { setEditingRecipeId(undefined); setTab("recipe-editor"); }}
              onEditRecipe={(docId) => { setEditingRecipeId(docId); setTab("recipe-editor"); }}
            />
          ) : (
            <DocumentList
              refreshKey={docRefreshKey}
              onChange={refreshHealth}
              onSelectDoc={handleSelectDoc}
            />
          )}
        </main>
      </div>

      {/* 导入对话框 */}
      {showImport && (
        <ImportDialog
          onClose={() => setShowImport(false)}
          onImported={refreshDocs}
        />
      )}
    </div>
  );
}
