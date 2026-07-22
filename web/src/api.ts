// Hermes KB API 客户端

import type {
  BatchImportResult,
  CategoryInfo,
  DocumentDetail,
  DocumentItem,
  HealthStatus,
  HistoryItem,
  LabDashboard,
  LabDailyRecipe,
  LabHotRecipe,
  LabMatchResult,
  LabRecipe,
  LabRecipeInput,
  LabRecipeVariant,
  LabSyncResult,
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

  // -------------------------------------------------------------------------
  // M3-M4 实验室：18 个 /api/lab/* 端点
  // -------------------------------------------------------------------------
  // 1. GET /api/lab/match — 材料匹配
  async labMatch(ingredients: string[]): Promise<LabMatchResult> {
    const qs = ingredients.length
      ? `?ingredients=${encodeURIComponent(ingredients.join(","))}`
      : "";
    return request<LabMatchResult>(`/api/lab/match${qs}`);
  },

  // 2. GET /api/lab/hot — 本周热门配方
  async labHot(limit?: number, days?: number): Promise<{ items: LabHotRecipe[] }> {
    const params = new URLSearchParams();
    if (limit) params.set("limit", String(limit));
    if (days) params.set("days", String(days));
    const qs = params.toString();
    return request(`/api/lab/hot${qs ? "?" + qs : ""}`);
  },

  // 3. POST /api/lab/view/{doc_id} — 记录配方查看
  async labView(docId: string): Promise<{ doc_id: string; status: string }> {
    return request(`/api/lab/view/${encodeURIComponent(docId)}`, { method: "POST" });
  },

  // 4. GET /api/lab/daily — 今日推荐
  async labDaily(): Promise<LabDailyRecipe> {
    return request<LabDailyRecipe>("/api/lab/daily");
  },

  // 5. GET /api/lab/missing-stats — 缺料统计
  async labMissingStats(limit?: number): Promise<{
    items: Array<{ canonical: string; missing_count: number; last_missing_at?: string | null }>;
  }> {
    const qs = limit ? `?limit=${limit}` : "";
    return request(`/api/lab/missing-stats${qs}`);
  },

  // 6. POST /api/lab/substitute — 用户提交替代材料
  async labSaveSubstitute(
    canonical: string,
    substitute: string
  ): Promise<{ canonical: string; substitute: string; status: string }> {
    return request("/api/lab/substitute", {
      method: "POST",
      body: JSON.stringify({ canonical, substitute }),
    });
  },

  // 7. GET /api/lab/dashboard — 实验室仪表盘
  async labDashboard(): Promise<LabDashboard> {
    return request<LabDashboard>("/api/lab/dashboard");
  },

  // 8. POST /api/lab/sync — 外部数据源同步
  async labSync(source: string, limit?: number): Promise<LabSyncResult> {
    const body: Record<string, unknown> = { source };
    if (limit !== undefined) body.limit = limit;
    return request<LabSyncResult>("/api/lab/sync", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  // 9. GET /api/lab/recipes — 配方治理列表
  async labRecipes(params?: {
    source?: string;
    verified?: boolean;
    hidden?: boolean;
    status?: string;
    limit?: number;
  }): Promise<{ items: LabRecipe[] }> {
    const sp = new URLSearchParams();
    if (params?.source) sp.set("source", params.source);
    if (params?.verified !== undefined) sp.set("verified", String(params.verified));
    if (params?.hidden !== undefined) sp.set("hidden", String(params.hidden));
    if (params?.status) sp.set("status", params.status);
    if (params?.limit !== undefined) sp.set("limit", String(params.limit));
    const qs = sp.toString();
    return request(`/api/lab/recipes${qs ? "?" + qs : ""}`);
  },

  // 10. POST /api/lab/recipes/{doc_id}/verify — 标记已验证
  async labVerifyRecipe(docId: string): Promise<{ doc_id: string; status: string }> {
    return request(`/api/lab/recipes/${encodeURIComponent(docId)}/verify`, { method: "POST" });
  },

  // 11. POST /api/lab/recipes/{doc_id}/hide?hidden= — 隐藏/取消隐藏
  async labHideRecipe(
    docId: string,
    hidden: boolean
  ): Promise<{ doc_id: string; hidden: boolean }> {
    return request(
      `/api/lab/recipes/${encodeURIComponent(docId)}/hide?hidden=${hidden}`,
      { method: "POST" }
    );
  },

  // 12. POST /api/lab/recipes — 创建 UGC 配方
  async labCreateRecipe(data: LabRecipeInput): Promise<{ doc_id: string; status: string; title: string }> {
    return request("/api/lab/recipes", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  // 13. PUT /api/lab/recipes/{doc_id} — 编辑（仅 draft）
  async labUpdateRecipe(
    docId: string,
    data: Partial<LabRecipeInput>
  ): Promise<{ doc_id: string; status: string }> {
    return request(`/api/lab/recipes/${encodeURIComponent(docId)}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  // 14. POST /api/lab/recipes/{doc_id}/submit — 提交审核（draft→pending）
  async labSubmitRecipe(docId: string): Promise<{ doc_id: string; status: string }> {
    return request(`/api/lab/recipes/${encodeURIComponent(docId)}/submit`, { method: "POST" });
  },

  // 15. POST /api/lab/recipes/{doc_id}/approve — 审核通过（pending→published）
  async labApproveRecipe(docId: string): Promise<{ doc_id: string; status: string }> {
    return request(`/api/lab/recipes/${encodeURIComponent(docId)}/approve`, { method: "POST" });
  },

  // 16. POST /api/lab/recipes/{doc_id}/reject — 审核驳回（pending→rejected）
  async labRejectRecipe(
    docId: string,
    reason?: string
  ): Promise<{ doc_id: string; status: string; reason?: string }> {
    return request(`/api/lab/recipes/${encodeURIComponent(docId)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || "" }),
    });
  },

  // 17. GET /api/lab/recipes/{doc_id}/variants — 配方变体列表
  async labListVariants(docId: string): Promise<{ items: LabRecipeVariant[]; count: number }> {
    return request(`/api/lab/recipes/${encodeURIComponent(docId)}/variants`);
  },

  // 18. POST /api/lab/recipes/{doc_id}/variant — 创建变体关联
  async labCreateVariant(
    docId: string,
    data: { variant_doc_id: string; variant_note: string }
  ): Promise<{ base_doc_id: string; variant_doc_id: string; status: string }> {
    return request(`/api/lab/recipes/${encodeURIComponent(docId)}/variant`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
};
