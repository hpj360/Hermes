import { useEffect, useState } from "react";
import { api } from "./api";
import type { HealthStatus } from "./types";
import { AgeGate } from "./components/AgeGate";
import { Login } from "./components/Login";
import { ChatPanel } from "./components/ChatPanel";
import { DocumentList } from "./components/DocumentList";
import { ImportDialog } from "./components/ImportDialog";

type Tab = "chat" | "docs";

export default function App() {
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [needLogin, setNeedLogin] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");
  const [showImport, setShowImport] = useState(false);
  const [docRefreshKey, setDocRefreshKey] = useState(0);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

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
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        加载中...
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

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* 顶部栏 */}
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="text-2xl">🍷</div>
          <div>
            <h1 className="font-bold text-gray-900">Hermes 知识库</h1>
            {health && (
              <p className="text-xs text-gray-500">
                {health.doc_count} 篇文档 ·{" "}
                <span className={health.llm_available ? "text-green-600" : "text-yellow-600"}>
                  LLM: {health.llm_provider}{health.llm_available ? "" : "（mock）"}
                </span>{" "}
                ·{" "}
                <span className={health.embedding_available ? "text-green-600" : "text-yellow-600"}>
                  Embed: {health.embedding_provider}{health.embedding_available ? "" : "（hash）"}
                </span>
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
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
          } md:block w-48 bg-white border-r flex-shrink-0`}
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
            <ChatPanel refreshDocs={refreshDocs} />
          ) : (
            <DocumentList refreshKey={docRefreshKey} onChange={refreshHealth} />
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
