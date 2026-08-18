// 轻量 fetch 封装：统一 JSON 处理、错误抛出与 Bearer 鉴权。
//
// API 基址约定（PRD v4 §5）：
//   /api/*  → content_team 业务（选题/创作/发布）
//   /wb/*   → workbench（jobs/todos/memory/skills/health）
const API_BASE = "/api";
const WB_BASE = "/wb";

export const TOKEN_KEY = "hermes_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.error ?? body.detail ?? detail;
    } catch {
      // ignore parse failure
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

export function get<T>(path: string, opts?: { wb?: boolean }): Promise<T> {
  return request<T>(opts?.wb ? WB_BASE : API_BASE, path);
}

export function post<T>(path: string, body?: unknown, opts?: { wb?: boolean }): Promise<T> {
  return request<T>(opts?.wb ? WB_BASE : API_BASE, path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function patch<T>(path: string, body: unknown, opts?: { wb?: boolean }): Promise<T> {
  return request<T>(opts?.wb ? WB_BASE : API_BASE, path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function del<T>(path: string, opts?: { wb?: boolean }): Promise<T> {
  return request<T>(opts?.wb ? WB_BASE : API_BASE, path, { method: "DELETE" });
}
