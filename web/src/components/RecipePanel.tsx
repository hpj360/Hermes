import { useEffect, useState } from "react";
import { api } from "../api";
import type { LabRecipe } from "../types";
import { PendingReviewPanel } from "./PendingReviewPanel";
import { SkeletonList } from "./Skeleton";

interface RecipePanelProps {
  /** 打开 UGC 编辑器（外部通过 tab 切换实现，组件本身只发请求）。 */
  onCreateRecipe?: () => void;
  /** 编辑已有配方。 */
  onEditRecipe?: (docId: string) => void;
}

const SOURCE_OPTIONS = [
  { value: "", label: "全部来源" },
  { value: "local", label: "本地" },
  { value: "iba_dataset", label: "IBA 金标准" },
  { value: "thecocktaildb", label: "TheCocktailDB" },
  { value: "ugc", label: "用户投稿" },
];

const VERIFIED_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "true", label: "已审核" },
  { value: "false", label: "待审核" },
];

const HIDDEN_OPTIONS = [
  { value: "", label: "全部可见性" },
  { value: "false", label: "仅可见" },
  { value: "true", label: "仅隐藏" },
];

/** M4 配方治理面板：筛选 + 卡片网格 + verify/hide 操作 + 待审核队列。 */
export function RecipePanel({ onCreateRecipe, onEditRecipe }: RecipePanelProps) {
  const [items, setItems] = useState<LabRecipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [filterVerified, setFilterVerified] = useState("");
  const [filterHidden, setFilterHidden] = useState("");
  const [search, setSearch] = useState("");
  const [busyDocId, setBusyDocId] = useState<string | null>(null);
  const [reviewTick, setReviewTick] = useState(0);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const params: Parameters<typeof api.labRecipes>[0] = { limit: 200 };
      if (filterSource) params.source = filterSource;
      if (filterVerified === "true") params.verified = true;
      else if (filterVerified === "false") params.verified = false;
      if (filterHidden === "true") params.hidden = true;
      else if (filterHidden === "false") params.hidden = false;
      const resp = await api.labRecipes(params);
      setItems(resp.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [filterSource, filterVerified, filterHidden]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = search
    ? items.filter((r) => (r.title || "").toLowerCase().includes(search.toLowerCase()))
    : items;

  const handleVerify = async (docId: string) => {
    setBusyDocId(docId);
    try {
      await api.labVerifyRecipe(docId);
      await load();
      setReviewTick((t) => t + 1);
    } catch (err) {
      alert(`审核失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setBusyDocId(null);
    }
  };

  const handleToggleHide = async (recipe: LabRecipe) => {
    setBusyDocId(recipe.doc_id);
    try {
      await api.labHideRecipe(recipe.doc_id, !recipe.hidden);
      await load();
    } catch (err) {
      alert(`操作失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setBusyDocId(null);
    }
  };

  const clearFilters = () => {
    setFilterSource("");
    setFilterVerified("");
    setFilterHidden("");
    setSearch("");
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-baseline justify-between mb-4 border-b border-ink-200 pb-3">
        <h2 className="text-2xl font-bold text-brand-700">📝 配方治理</h2>
        <span className="text-xs text-gray-400">外部数据源 / 审核 / 隐藏</span>
      </div>

      {/* 待审核队列（status=pending 自动加载） */}
      <PendingReviewPanel
        refreshTick={reviewTick}
        onResolved={() => {
          load();
          setReviewTick((t) => t + 1);
        }}
      />

      {/* 筛选栏 */}
      <div className="card p-4 mb-4">
        <div className="flex items-center gap-3 flex-wrap">
          <select
            className="text-sm border border-gray-300 rounded px-2 py-1 bg-white min-w-[140px]"
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value)}
            aria-label="来源筛选"
          >
            {SOURCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            className="text-sm border border-gray-300 rounded px-2 py-1 bg-white"
            value={filterVerified}
            onChange={(e) => setFilterVerified(e.target.value)}
            aria-label="审核状态筛选"
          >
            {VERIFIED_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            className="text-sm border border-gray-300 rounded px-2 py-1 bg-white"
            value={filterHidden}
            onChange={(e) => setFilterHidden(e.target.value)}
            aria-label="可见性筛选"
          >
            {HIDDEN_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <input
            type="search"
            className="input flex-1 min-w-[160px]"
            placeholder="搜索配方名…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="配方搜索"
          />
          {(filterSource || filterVerified || filterHidden || search) && (
            <button
              type="button"
              onClick={clearFilters}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              清除
            </button>
          )}
          <span className="ml-auto text-sm text-gold-700">
            共 <span className="text-lg font-semibold text-gold-500">{filtered.length}</span> 款
          </span>
          {onCreateRecipe && (
            <button
              type="button"
              onClick={onCreateRecipe}
              className="btn-primary text-sm"
            >
              + 创作配方
            </button>
          )}
        </div>
      </div>

      {/* 错误 */}
      {error && (
        <div className="card p-6 mb-4 text-center text-red-600">加载失败：{error}</div>
      )}

      {/* 加载中 — F3: 骨架屏替代纯文字 */}
      {loading && items.length === 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <SkeletonList count={6} />
        </div>
      )}

      {/* 空状态 */}
      {!loading && filtered.length === 0 && !error && (
        <div className="text-center py-12 text-gray-400">
          <div className="text-3xl mb-2">◆</div>
          <div className="text-sm">暂无配方，请先同步外部数据源或创作新配方</div>
        </div>
      )}

      {/* 配方卡片网格 */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((r) => (
            <RecipeCard
              key={r.doc_id}
              recipe={r}
              busy={busyDocId === r.doc_id}
              onVerify={() => handleVerify(r.doc_id)}
              onToggleHide={() => handleToggleHide(r)}
              onEdit={onEditRecipe ? () => onEditRecipe(r.doc_id) : undefined}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface RecipeCardProps {
  recipe: LabRecipe;
  busy: boolean;
  onVerify: () => void;
  onToggleHide: () => void;
  onEdit?: () => void;
}

function RecipeCard({ recipe, busy, onVerify, onToggleHide, onEdit }: RecipeCardProps) {
  const statusText = (() => {
    switch (recipe.status) {
      case "draft": return "草稿";
      case "pending": return "待审核";
      case "published": return "已发布";
      case "rejected": return "已驳回";
      default: return recipe.status;
    }
  })();
  const statusClass = (() => {
    switch (recipe.status) {
      case "published": return "bg-brand-50 text-brand-700";
      case "pending": return "bg-gold-100 text-gold-700";
      case "rejected": return "bg-red-50 text-red-600";
      default: return "bg-ink-100 text-ink-600";
    }
  })();

  return (
    <div
      className={`card p-4 flex flex-col gap-2 hover:shadow-md transition-shadow ${
        recipe.hidden ? "opacity-55" : ""
      }`}
      data-doc-id={recipe.doc_id}
    >
      <div className="flex items-start justify-between gap-2">
        <h3
          className="text-base font-semibold text-ink-900 truncate flex-1"
          title={recipe.title}
        >
          {recipe.title || "(未命名)"}
        </h3>
        <span className={`text-xs px-2 py-0.5 rounded-full ${statusClass}`}>
          {statusText}
        </span>
      </div>
      <div className="flex gap-2 flex-wrap items-center text-xs">
        <span className="px-1.5 py-0.5 rounded bg-brand-50 text-brand-700">
          {recipe.source || "local"}
        </span>
        {recipe.verified ? (
          <span className="px-1.5 py-0.5 rounded bg-green-50 text-green-700">✓ 已审核</span>
        ) : (
          <span className="px-1.5 py-0.5 rounded bg-ink-100 text-ink-600">待审核</span>
        )}
        {recipe.hidden && (
          <span className="px-1.5 py-0.5 rounded bg-red-50 text-red-600">隐藏</span>
        )}
        {recipe.season && (
          <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">{recipe.season}</span>
        )}
      </div>
      <div className="text-xs text-gray-400 break-all" title={recipe.doc_id}>
        {recipe.doc_id}
      </div>
      <div className="flex gap-2 pt-2 border-t border-dashed border-ink-100">
        {!recipe.verified && (
          <button
            type="button"
            onClick={onVerify}
            disabled={busy}
            className="text-xs px-2 py-1 rounded border border-ink-200 hover:border-brand-700 hover:text-brand-700 disabled:opacity-50"
          >
            审核通过
          </button>
        )}
        <button
          type="button"
          onClick={onToggleHide}
          disabled={busy}
          className="text-xs px-2 py-1 rounded border border-ink-200 hover:border-gold-700 hover:text-gold-700 disabled:opacity-50"
        >
          {recipe.hidden ? "取消隐藏" : "隐藏"}
        </button>
        {onEdit && (recipe.status === "draft" || recipe.status === "rejected") && (
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            className="text-xs px-2 py-1 rounded border border-ink-200 hover:border-brand-700 hover:text-brand-700 disabled:opacity-50 ml-auto"
          >
            编辑
          </button>
        )}
      </div>
    </div>
  );
}
