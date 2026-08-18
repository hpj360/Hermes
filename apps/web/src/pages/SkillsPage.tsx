import { useEffect, useState } from "react";
import { get, post } from "../api";

interface Skill {
  name: string;
  runtime: string;
  description: string;
  path: string;
}

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    get<{ skills: Skill[] }>("/skills", { wb: true })
      .then((d) => setSkills(d.skills ?? []))
      .catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, []);

  const run = async (name: string) => {
    setLoading(true);
    try {
      const result = await post<{ ok: boolean; stdout?: string; error?: string }>(
        `/skills/${name}/run`,
        { args: [] },
        { wb: true },
      );
      alert(result.ok ? `运行成功:\n${result.stdout ?? "(无输出)"}` : `运行失败:\n${result.error}`);
    } catch (e) {
      alert(`运行失败: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white border rounded-lg p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">技能中心</h2>
        <button className="px-3 py-1.5 rounded bg-gray-100 text-sm" onClick={refresh}>
          刷新
        </button>
      </div>
      {skills.length === 0 ? (
        <p className="text-sm text-gray-400">{loading ? "加载中…" : "未发现技能。"}</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-3 py-2">技能</th>
              <th className="px-3 py-2">运行时</th>
              <th className="px-3 py-2">说明</th>
              <th className="px-3 py-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {skills.map((s) => (
              <tr key={s.name} className="border-t">
                <td className="px-3 py-2 font-medium">{s.name}</td>
                <td className="px-3 py-2 text-gray-500">{s.runtime}</td>
                <td className="px-3 py-2 text-gray-600">{s.description}</td>
                <td className="px-3 py-2">
                  <button className="px-2 py-1 rounded bg-gray-100 text-xs" onClick={() => run(s.name)}>
                    运行
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
