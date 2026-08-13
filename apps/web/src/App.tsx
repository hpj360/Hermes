import { Link, Route, Switch } from "wouter";
import ContentPage from "./pages/ContentPage";
import PublishPage from "./pages/PublishPage";
import TopicsPage from "./pages/TopicsPage";

const NAV = [
  { href: "/topics", label: "选题" },
  { href: "/content", label: "创作" },
  { href: "/publish", label: "发布" },
];

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-brand-600 text-white shadow">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-6">
          <h1 className="text-lg font-semibold">Content-Team</h1>
          <nav className="flex gap-1">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="px-3 py-1.5 rounded hover:bg-brand-500 text-sm"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-6xl w-full mx-auto px-4 py-6">
        <Switch>
          <Route path="/topics" component={TopicsPage} />
          <Route path="/content" component={ContentPage} />
          <Route path="/publish" component={PublishPage} />
          <Route>
            <TopicsPage />
          </Route>
        </Switch>
      </main>
    </div>
  );
}
