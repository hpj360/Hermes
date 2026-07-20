import { useState } from "react";
import { api } from "../api";

interface LoginProps {
  onLogin: () => void;
}

/** 登录页（M1-07）：单用户密码认证。 */
export function Login({ onLogin }: LoginProps) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await api.login(password);
      if (!result.auth_enabled) {
        // 未启用认证直接进入
        onLogin();
        return;
      }
      api.setToken(result.token);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-50 to-gray-100">
      <div className="card max-w-sm w-full mx-4 p-8">
        <div className="text-center mb-6">
          <div className="text-4xl mb-2">🍷</div>
          <h1 className="text-2xl font-bold text-gray-900">Hermes 知识库</h1>
          <p className="text-sm text-gray-500 mt-1">请输入访问密码</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="password"
            className="input"
            placeholder="密码"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            disabled={loading}
          />
          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>
          )}
          <button
            type="submit"
            className="btn-primary w-full"
            disabled={loading || !password}
          >
            {loading ? "登录中..." : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
