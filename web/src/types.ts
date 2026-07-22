// Hermes KB 前端类型定义

export interface Citation {
  id: number;
  doc_id: string;
  title: string;
  snippet: string;
  score: number;
  chunk_rowid: number;
}

export interface RAGAnswer {
  answer_id: string;
  query: string;
  answer: string;
  citations: Citation[];
  model_used: string;
  latency_ms: number;
  rejected: boolean;
  low_confidence: boolean;
}

export interface DocumentItem {
  doc_id: string;
  title: string;
  source_type: string;
  file_type: string;
  chunk_count: number;
  category: string;
  tags: TagInfo[];
  created_at: string | null;
}

export interface TagInfo {
  id: number;
  name: string;
  color: string;
  doc_count?: number;
}

export interface CategoryInfo {
  name: string;
  doc_count: number;
}

export interface ChunkInfo {
  rowid: number;
  idx: number;
  text: string;
  char_start: number;
  char_end: number;
}

export interface DocumentDetail {
  doc: {
    doc_id: string;
    title: string;
    source_type: string;
    file_type: string;
    chunk_count: number;
    category: string;
    content_length: number;
    created_at: string | null;
  };
  tags: TagInfo[];
  chunks: ChunkInfo[];
}

export interface BatchImportResult {
  total: number;
  imported: number;
  failed: number;
  results: Array<{
    filename: string;
    status: "imported" | "failed";
    doc_id?: string;
    chunk_count?: number;
    error?: string;
  }>;
}

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  time?: string;
  doc_count: number;
  llm_provider: string;
  llm_available: boolean;
  embedding_provider: string;
  embedding_available: boolean;
  auth_enabled: boolean;
  age_gate_enabled: boolean;
}

export interface HistoryItem {
  id: number;
  query: string;
  answer: string;
  citations: Citation[];
  model_used: string;
  latency_ms: number;
  feedback: number;
  created_at: string | null;
}

export interface SeedResult {
  seeded: number;
  failed: number;
  items: Array<Record<string, unknown>>;
}

// SSE 流式事件
export type SSEEvent =
  | { type: "meta"; answer_id: string; citations: Citation[]; rejected: boolean; low_confidence: boolean; model_used: string }
  | { type: "delta"; content: string }
  | { type: "done"; latency_ms: number }
  | { type: "error"; message: string };

// ---------------------------------------------------------------------------
// M3-M4 实验室 / 配方治理 / UGC 类型
// 类型定义依据后端 src/hermes_kb/ 实际响应结构（full_match/partial_match/ingredients[]）
// ---------------------------------------------------------------------------

/** 单个材料的详情（have 表示用户已选，substitutes 为可选替代表） */
export interface LabMatchIngredient {
  name: string;
  have: boolean;
  substitutes?: string[];
}

/** /api/lab/match 返回的单条配方匹配项 */
export interface LabMatchItem {
  doc_id: string;
  title: string;
  chunk_rowid?: number;
  ingredients: LabMatchIngredient[];
  base_spirit?: string;
  difficulty?: string;
  match_count?: number;       // full_match 携带
  missing?: string[];         // partial_match 携带
  missing_count?: number;     // partial_match 携带
}

/** /api/lab/match 响应 */
export interface LabMatchResult {
  full_match: LabMatchItem[];
  partial_match: LabMatchItem[];
}

/** /api/lab/daily 响应（每日推荐） */
export interface LabDailyRecipe {
  title: string | null;
  reason: string;            // season / hot / random / empty
  doc_id?: string;
  chunk_rowid?: number;
  base_spirit?: string;
  difficulty?: string;
}

/** /api/lab/hot 单条热门配方 */
export interface LabHotRecipe {
  doc_id: string;
  title: string;
  chunk_rowid?: number;
  match_count: number;
  last_matched_at?: string | null;
}

/** /api/lab/recipes 单条配方（治理列表） */
export interface LabRecipe {
  doc_id: string;
  title: string;
  source: string;            // local / iba_dataset / thecocktaildb / ugc
  source_id?: string;
  verified: boolean;
  hidden: boolean;
  status: string;            // draft / pending / published / rejected
  season?: string | null;
  image_url?: string | null;
}

/** POST /api/lab/recipes 创建 / PUT 编辑请求体 */
export interface LabRecipeInput {
  title: string;
  ingredients: string[];
  content: string;
  base_spirit?: string;
  difficulty?: string;
  season?: string | null;
}

/** /api/lab/recipes/{doc_id}/variants 单条变体 */
export interface LabRecipeVariant {
  variant_doc_id: string;
  variant_title: string;
  variant_note: string;
  created_at?: string | null;
}

/** /api/lab/dashboard 实验室运营指标 */
export interface LabDashboard {
  recipe_count?: number;
  weekly_match_count?: number;
  total_match_count?: number;
  top_recipe?: string | null;
  top_missing?: {
    canonical: string;
    missing_count: number;
    last_missing_at?: string | null;
  } | null;
  substitute_coverage?: number;
  user_substitute_count?: number;
  daily_recipe?: string | null;
  season_coverage?: number;
  [key: string]: any;
}

/** /api/lab/sync 同步结果（result 字段随 source 变化） */
export interface LabSyncResult {
  source: string;
  imported?: number;
  skipped?: number;
  failed?: number;
  unknown_ingredients?: string[];
  [key: string]: any;
}
