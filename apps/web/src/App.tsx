import { Link, Route, Switch } from "wouter";
import DashboardPage from "./pages/DashboardPage";
import CapturePage from "./pages/CapturePage";
import JobsPage from "./pages/JobsPage";
import MemoryPage from "./pages/MemoryPage";
import ContentPage from "./pages/ContentPage";
import PublishPage from "./pages/PublishPage";
import TopicsPage from "./pages/TopicsPage";
import SkillsPage from "./pages/SkillsPage";
import { TOKEN_KEY } from "./api";

const NAV = [
  { href: "/", label: "驾驶舱" },
  { href: "/capture", label: "捕获" },
  { href: "/jobs", label: "任务运行" },
  { href: "/memory", label: "记忆" },
  { href: "/topics", label: "内容" },
  { href: "/skills", label: "技能" },
];

function Settings() {
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  return (
    <div className="p-6 max-w-xl">
      <h2 className="text-xl font-semibold mb-4">设置</h2>
      <label className="block text-sm text-gray-600 mb-1">API Token (HERMES_API_TOKEN)</label>
      <input
        className="w-full border rounded px-3 py-2 mb-3 font-mono text-sm"
        placeholder="留空则使用本地无鉴权模式"
        value={token}
        onChange={(e) => {
          const v = e.target.value.trim();
          if (v) localStorage.setItem(TOKEN_KEY, v);
          else localStorage.removeItem(TOKEN_KEY);
        }}
      />
      <p className="text-xs text-gray-500">Token 仅保存在本机浏览器 localStorage。</p>
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <header className="bg-slate-900 text-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-6">
          <h1 className="text-lg font-semibold">Hermes Workbench</h1>
          <nav className="flex gap-1 flex-1">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="px-3 py-1.5 rounded hover:bg-slate-700 text-sm"
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <Link href="/settings" className="px-3 py-1.5 rounded hover:bg-slate-700 text-sm">
            ⚙ 设置
          </Link>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
        <Switch>
          <Route path="/" component={DashboardPage} />
          <Route path="/capture" component={CapturePage} />
          <Route path="/jobs" component={JobsPage} />
          <Route path="/memory" component={MemoryPage} />
          <Route path="/topics" component={TopicsPage} />
          <Route path="/content" component={ContentPage} />
          <Route path="/publish" component={PublishPage} />
          <Route path="/skills" component={SkillsPage} />
          <Route path="/settings" component={Settings} />
          <Route>
            <DashboardPage />
          </Route>
        </Switch>
      </main>
    </div>
  );
}
