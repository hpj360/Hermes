import { useEffect, useState } from "react";
import { api } from "../api";

interface AgeGateProps {
  onConfirm: () => void;
}

/** 年龄门（M1-08）：未满 18 岁请勿访问。 */
export function AgeGate({ onConfirm }: AgeGateProps) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.ageGateStatus().then((s) => {
      setEnabled(s.age_gate_enabled);
      setMessage(s.message);
      // 未启用年龄门直接放行
      if (!s.age_gate_enabled) onConfirm();
    }).catch(() => {
      // 接口失败也放行，避免阻塞
      onConfirm();
    });
  }, [onConfirm]);

  if (enabled === null || !enabled) {
    return null;
  }

  const handleConfirm = async (confirmed: boolean) => {
    setLoading(true);
    try {
      await api.ageGateConfirm(confirmed);
      if (confirmed) onConfirm();
      else window.location.href = "about:blank";
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="card max-w-md w-full mx-4 p-8 text-center">
        <div className="text-5xl mb-4">🍷</div>
        <h2 className="text-2xl font-bold mb-3 text-gray-900">年龄确认</h2>
        <p className="text-gray-600 mb-2">{message}</p>
        <p className="text-sm text-gray-500 mb-6">
          本站内容含酒类知识，依据相关法律法规，未满 18 岁请勿访问。
        </p>
        <div className="flex gap-3">
          <button
            className="btn-secondary flex-1"
            onClick={() => handleConfirm(false)}
            disabled={loading}
          >
            我未满 18 岁
          </button>
          <button
            className="btn-primary flex-1"
            onClick={() => handleConfirm(true)}
            disabled={loading}
          >
            我已满 18 岁
          </button>
        </div>
      </div>
    </div>
  );
}
