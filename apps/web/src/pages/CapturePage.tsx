import { useEffect, useState } from "react";
import { get, post } from "../api";

interface Todo {
  todo_id: string;
  title: string;
  type: string;
  status: string;
  source: string;
  job_id?: string;
}

const TYPES = [
  ["idea", "灵感"],
  ["link", "摘记/链接"],
  ["fact", "事实"],
  ["todo", "待办"],
] as const;

export default function CapturePage() {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<string>("idea");
  const [todos, setTodos] = useState<Todo[]>([]);

  const refresh = () => {
    get<{ todos: Todo[] }>("/todos", { wb: true }).then((d) => setTodos(d.todos)).catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, []);

  const onAdd = async () => {
    const t = title.trim();
    if (!t) return;
    setTitle("");
    try {
      await post("/inbox", { title: t, type, source: "inbox" }, { wb: true });
      refresh();
    } catch (e) {
      alert(`捕获失败: ${(e as Error).message}`);
    }
  };

  return (
    <div className="max-w-3xl">
      <h2 className="text-xl font-semibold mb-4">捕获</h2>
      <div className="bg-white border rounded-lg p-4 mb-4">
        <p className="text-sm text-gray-500 mb-2">
          记灵感、存链接、记事实、列待办——1 秒完成。带链接的条目会自动生成摘要任务。
        </p>
        <div className="flex gap-2">
          <select
            className="border rounded px-2 py-1.5 text-sm"
            value={type}
            onChange={(e) => setType(e.target.value)}
          >
            {TYPES.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
          <input
            className="flex-1 border rounded px-3 py-1.5 text-sm"
            placeholder="输入内容或粘贴链接…"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAdd()}
          />
          <button className="px-4 py-1.5 rounded bg-slate-900 text-white text-sm" onClick={onAdd}>
            捕获
          </button>
        </div>
      </div>

      <div className="bg-white border rounded-lg p-4">
        <h3 className="font-semibold mb-2">未整理列表</h3>
        {todos.length === 0 ? (
          <p className="text-sm text-gray-400">还没有捕获内容。用上面输入框记一条。</p>
        ) : (
          <ul className="divide-y">
            {todos.map((t) => (
              <li key={t.todo_id} className="py-2 flex items-center justify-between gap-2 text-sm">
                <div>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 mr-2">
                    {TYPES.find(([v]) => v === t.type)?.[1] ?? t.type}
                  </span>
                  <span className={t.status === "DONE" ? "line-through text-gray-400" : ""}>{t.title}</span>
                  {t.job_id && <span className="text-xs text-blue-600 ml-2">→ {t.job_id.slice(0, 8)}</span>}
                </div>
                <div className="flex gap-1">
                  {t.status !== "DONE" && (
                    <button
                      className="px-2 py-1 rounded bg-gray-100 text-xs"
                      onClick={async () => {
                        await post(`/todos/${t.todo_id}/status`, { status: "done" }, { wb: true }).catch(() => {});
                        refresh();
                      }}
                    >
                      完成
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
