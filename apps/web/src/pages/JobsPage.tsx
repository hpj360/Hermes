import { useEffect, useState } from "react";
import { get, post } from "../api";

interface Job {
  job_id: string;
  status: string;
  target_project: string;
  priority: number;
  created_at?: string;
  attempts?: { status: string; error?: string }[];
}

const VIEWS = [
  ["attention", "需关注"],
  ["running", "进行中"],
  ["done", "已完成"],
  ["all", "全部"],
] as const;

const ACTIVE = new Set(["PENDING", "QUEUED", "RUNNING"]);
const NEEDS_ATTENTION = new Set(["PENDING", "QUEUED", "RUNNING", "FAILED", "TIMEOUT", "ABANDONED"]);
const DONE = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT", "ABANDONED"]);

function bucket(job: Job): "running" | "success" | "attention" {
  if (job.status === "SUCCEEDED") return "success";
  if (job.status === "FAILED" || job.status === "TIMEOUT" || job.status === "ABANDONED") return "attention";
  return "running";
}

const BUCKET_STYLE: Record<string, string> = {
  running: "bg-blue-100 text-blue-700",
  success: "bg-green-100 text-green-700",
  attention: "bg-red-100 text-red-700",
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [view, setView] = useState<string>("attention");
  const [plan, setPlan] = useState<string>('[{"skill":"weather","args":["Beijing"]}]');

  const refresh = () => {
    get<{ jobs: Job[] }>("/jobs", { wb: true })
      .then((d) => setJobs(d.jobs ?? []))
      .catch(() => {});
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, []);

  const visible = jobs.filter((j) => {
    if (view === "attention") return NEEDS_ATTENTION.has(j.status);
    if (view === "running") return ACTIVE.has(j.status);
    if (view === "done") return DONE.has(j.status);
    return true;
  });

  const count = (f: (j: Job) => boolean) => jobs.filter(f).length;

  const submit = async () => {
    try {
      const parsed = JSON.parse(plan);
      await post("/jobs", { plan: parsed }, { wb: true });
      setPlan('[{"skill":"weather","args":["Beijing"]}]');
      refresh();
    } catch (e) {
      alert(`提交失败: ${(e as Error).message}`);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        {VIEWS.map(([v, label]) => (
          <button
            key={v}
            className={`px-3 py-1.5 rounded text-sm ${view === v ? "bg-slate-900 text-white" : "bg-gray-100"}`}
            onClick={() => setView(v)}
          >
            {label} {count((j) => (v === "attention" ? NEEDS_ATTENTION.has(j.status) : true))}
          </button>
        ))}
      </div>

      <div className="bg-white border rounded-lg p-4 mb-4">
        <h3 className="font-semibold mb-2">提交 job</h3>
        <div className="flex gap-2">
          <input
            className="flex-1 border rounded px-3 py-1.5 font-mono text-sm"
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
          />
          <button className="px-4 py-1.5 rounded bg-slate-900 text-white text-sm" onClick={submit}>
            提交
          </button>
        </div>
      </div>

      <div className="bg-white border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2">job_id</th>
              <th className="px-3 py-2">状态</th>
              <th className="px-3 py-2">项目</th>
              <th className="px-3 py-2">优先级</th>
              <th className="px-3 py-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-gray-400">
                  当前视图无任务。
                </td>
              </tr>
            ) : (
              visible.map((j) => (
                <tr key={j.job_id} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">{j.job_id.slice(0, 12)}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs ${BUCKET_STYLE[bucket(j)]}`}>
                      {j.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">{j.target_project}</td>
                  <td className="px-3 py-2">P{j.priority}</td>
                  <td className="px-3 py-2">
                    {["FAILED", "TIMEOUT", "CANCELLED", "ABANDONED"].includes(j.status) && (
                      <button
                        className="px-2 py-1 rounded bg-gray-100 text-xs"
                        onClick={async () => {
                          await post(`/jobs/${j.job_id}/retry`, undefined, { wb: true }).catch((e) =>
                            alert((e as Error).message),
                          );
                          refresh();
                        }}
                      >
                        重试
                      </button>
                    )}
                    {ACTIVE.has(j.status) && (
                      <button
                        className="px-2 py-1 rounded bg-red-50 text-red-700 text-xs"
                        onClick={async () => {
                          await post(`/jobs/${j.job_id}/cancel`, undefined, { wb: true }).catch(() => {});
                          refresh();
                        }}
                      >
                        取消
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
