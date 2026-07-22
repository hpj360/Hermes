// Hermes KB API 客户端

import type {
  BatchImportResult,
  CategoryInfo,
  DocumentDetail,
  DocumentItem,
  HealthStatus,
  HistoryItem,
  RAGAnswer,
  SSEEvent,
  SeedResult,
  TagInfo,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE || "";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("hermes_kb_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail || body.error || detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return resp.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// 健康检查
// ---------------------------------------------------------------------------
export const api = {
  async health(): Promise<HealthStatus> {
    return request<HealthStatus>("/api/health");
  },

  // -------------------------------------------------------------------------
  // 文档管理
  // -------------------------------------------------------------------------
  async listDocuments(category?: string, tagId?: number): Promise<{ total: number; items: DocumentItem[] }> {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (tagId) params.set("tag_id", String(tagId));
    const qs = params.toString();
    return request(`/api/documents${qs ? "?" + qs : ""}`);
  },

  async importText(
    title: string,
    content: string,
    category?: string
  ): Promise<{ doc_id: string; status: string }> {
    return request("/api/documents/import-text", {
      method: "POST",
      body: JSON.stringify({
        title,
        content,
        source_type: "local",
        file_type: "txt",
        category: category || "",
      }),
    });
  },

  async uploadFile(file: File, title?: string): Promise<{ doc_id: string; status: string }> {
    const form = new FormData();
    form.append("file", file);
    if (title) form.append("title", title);
    const resp = await fetch(`${BASE}/api/documents/upload`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    if (!resp.ok) {
      throw new Error(`上传失败: HTTP ${resp.status}`);
    }
    return resp.json();
  },

  async uploadBatch(files: File[]): Promise<BatchImportResult> {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    const resp = await fetch(`${BASE}/api/documents/upload-batch`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    if (!resp.ok) {
      const txt = await resp.text();
      throw new Error(`批量上传失败: ${txt}`);
    }
    return resp.json();
  },

  async deleteDocument(docId: string): Promise<{ status: string }> {
    return request(`/api/documents/${docId}`, { method: "DELETE" });
  },

  // M2-03：文档详情
  async getDocument(docId: string): Promise<DocumentDetail> {
    return request(`/api/documents/${docId}`);
  },

  async downloadDocumentRaw(docId: string): Promise<void> {
    const resp = await fetch(`${BASE}/api/documents/${docId}/raw`, {
      headers: authHeaders(),
    });
    if (!resp.ok) throw new Error(`下载失败: HTTP ${resp.status}`);
    const blob = await resp.blob();
    const cd = resp.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="([^"]+)"/);
    const filename = m ? m[1] : `${docId}.txt`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // M2-06：元信息更新
  async updateDocMetadata(
    docId: string,
    data: { title?: string; category?: string; tag_ids?: number[] }
  ): Promise<{ status: string }> {
    return request(`/api/documents/${docId}/metadata`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  // M2-06：标签管理
  async listTags(): Promise<{ total: number; items: TagInfo[] }> {
    return request("/api/tags");
  },

  async createTag(name: string, color?: string): Promise<TagInfo> {
    return request("/api/tags", {
      method: "POST",
      body: JSON.stringify({ name, color: color || "#6b7280" }),
    });
  },

  async deleteTag(tagId: number): Promise<{ status: string }> {
    return request(`/api/tags/${tagId}`, { method: "DELETE" });
  },

  // M2-06：分类列表
  async listCategories(): Promise<{ total: number; items: CategoryInfo[] }> {
    return request("/api/categories");
  },

  // -------------------------------------------------------------------------
  // 问答
  // -------------------------------------------------------------------------
  async ask(query: string, topK?: number): Promise<RAGAnswer> {
    return request("/api/ask", {
      method: "POST",
      body: JSON.stringify({ query, top_k: topK }),
    });
  },

  async askStream(
    query: string,
    topK: number | undefined,
    onEvent: (event: SSEEvent) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const resp = await fetch(`${BASE}/api/ask/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeaders(),
      },
      body: JSON.stringify({ query, top_k: topK }),
      signal,
    });
    if (!resp.ok || !resp.body) {
      throw new Error(`流式问答失败: HTTP ${resp.status}`);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        try {
          const evt = JSON.parse(trimmed.slice(6)) as SSEEvent;
          onEvent(evt);
        } catch {
          // ignore malformed
        }
      }
    }
  },

  // -------------------------------------------------------------------------
  // 历史 + 反馈
  // -------------------------------------------------------------------------
  async history(limit = 50): Promise<{ total: number; items: HistoryItem[] }> {
    return request(`/api/history?limit=${limit}`);
  },

  async feedback(logId: number, feedback: number): Promise<{ status: string }> {
    return request(`/api/feedback/${logId}`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    });
  },

  // -------------------------------------------------------------------------
  // 种子数据
  // -------------------------------------------------------------------------
  async seed(): Promise<SeedResult> {
    return request("/api/seed", { method: "POST" });
  },

  // -------------------------------------------------------------------------
  // 认证
  // -------------------------------------------------------------------------
  async login(password: string): Promise<{ token: string; auth_enabled: boolean }> {
    return request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    });
  },

  async me(): Promise<{ auth_enabled: boolean; username: string | null }> {
    return request("/api/auth/me");
  },

  logout(): void {
    localStorage.removeItem("hermes_kb_token");
  },

  setToken(token: string): void {
    localStorage.setItem("hermes_kb_token", token);
  },

  getToken(): string | null {
    return localStorage.getItem("hermes_kb_token");
  },

  // -------------------------------------------------------------------------
  // 年龄门
  // -------------------------------------------------------------------------
  async ageGateStatus(): Promise<{ age_gate_enabled: boolean; message: string }> {
    return request("/api/age-gate/status");
  },

  async ageGateConfirm(confirmed: boolean): Promise<{ confirmed: boolean }> {
    return request("/api/age-gate/confirm", {
      method: "POST",
      body: JSON.stringify({ confirmed }),
    });
  },
};
