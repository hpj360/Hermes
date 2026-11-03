import { useEffect, useState } from "react";
import { get } from "../api";
import type { CalendarDay, Topic } from "../types";

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-gray-100 text-gray-600",
  IN_PROGRESS: "bg-blue-100 text-blue-700",
  PUBLISHED: "bg-green-100 text-green-700",
  ARCHIVED: "bg-gray-100 text-gray-400",
};

export default function CalendarPage() {
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [schedule, setSchedule] = useState<CalendarDay[]>([]);
  const [error, setError] = useState("");

  async function load() {
    try {
      const [all, cal] = await Promise.all([
        get<Topic[]>("/topics"),
        get<CalendarDay[]>("/topics/calendar?days=90"),
      ]);
      setTopics(all);
      setSchedule(cal);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const unscheduled = (topics ?? []).filter((t) => !t.planned_date);

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">发布日历</h2>
      {error && <p className="text-red-600 text-sm">{error}</p>}
      <p className="text-sm text-gray-500">
        在「选题」页给选题设置计划发布日，即可在这里查看滚动 90 天的排期节奏。
      </p>

      {schedule.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-6 text-sm text-gray-400">
          窗口内还没有排期。去「选题」页给选题挑一个发布日。
        </div>
      ) : (
        <ul className="space-y-3">
          {schedule.map((d) => (
            <li key={d.planned_date} className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium">{d.planned_date}</span>
                <span className="text-xs text-gray-500">{d.count} 篇</span>
              </div>
              <ul className="space-y-1">
                {d.topics.map((t) => (
                  <li
                    key={t.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <span>{t.title}</span>
                    <span className="flex items-center gap-1">
                      {t.target_platforms.length > 0 && (
                        <span className="text-xs text-gray-400">
                          {t.target_platforms.join(", ")}
                        </span>
                      )}
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs ${
                          STATUS_COLORS[t.status] ?? "bg-gray-100"
                        }`}
                      >
                        {t.status}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {unscheduled.length > 0 && (
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">
            未排期选题（{unscheduled.length}）
          </h3>
          <div className="flex flex-wrap gap-1">
            {unscheduled.slice(0, 30).map((t) => (
              <span
                key={t.id}
                className="bg-gray-50 border rounded px-2 py-0.5 text-xs text-gray-600"
              >
                {t.title}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
