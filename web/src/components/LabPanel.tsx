import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LabDailyRecipe, LabMatchItem, LabMatchResult } from "../types";

interface LabPanelProps {
  onJumpToDoc?: (docId: string, chunkRowid?: number) => void;
}

/** M3 实验室主面板：今日推荐 + 材料选择 + 匹配结果。 */
export function LabPanel({ onJumpToDoc }: LabPanelProps) {
  const [daily, setDaily] = useState<LabDailyRecipe | null>(null);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [search, setSearch] = useState("");
  const [result, setResult] = useState<LabMatchResult | null>(null);
  const [matching, setMatching] = useState(false);
  const [error, setError] = useState("");

  // 加载今日推荐
  useEffect(() => {
    let cancelled = false;
    api
      .labDaily()
      .then((d) => {
        if (!cancelled && d && d.title) setDaily(d);
      })
      .catch(() => {
        /* 静默：今日推荐为可选 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedNames = useMemo(() => Object.keys(selected), [selected]);

  const toggleMaterial = (name: string, category: string) => {
    setSelected((prev) => {
      const next = { ...prev };
      if (next[name]) {
        delete next[name];
      } else {
        next[name] = category;
      }
      return next;
    });
  };

  const clearAll = () => {
    setSelected({});
    setResult(null);
    setError("");
  };

  const quickSelect = (names: string[]) => {
    const next: Record<string, string> = {};
    for (const name of names) {
      const found = MATERIAL_CATEGORIES.find((c) =>
        c.items.some((it) => it === name)
      );
      if (found) next[name] = found.id;
    }
    setSelected(next);
    setResult(null);
    setError("");
  };

  const doMatch = async () => {
    if (selectedNames.length === 0) return;
    setMatching(true);
    setError("");
    try {
      const r = await api.labMatch(selectedNames);
      setResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : "匹配失败");
      setResult(null);
    } finally {
      setMatching(false);
    }
  };

  const reasonText = (reason?: string): string => {
    if (reason === "season") return "应季推荐";
    if (reason === "hot") return "本周热门";
    if (reason === "random") return "随机发现";
    return "今日推荐";
  };

  const filteredCategories = useMemo(() => {
    if (!search.trim()) return MATERIAL_CATEGORIES;
    const q = search.trim().toLowerCase();
    return MATERIAL_CATEGORIES.map((c) => ({
      ...c,
      items: c.items.filter((it) => it.toLowerCase().includes(q)),
    })).filter((c) => c.items.length > 0);
  }, [search]);

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6 text-center">
        <h2 className="text-2xl font-bold text-brand-700 mb-1">🧪 鸡尾酒实验室</h2>
        <p className="text-sm text-gray-500">选择手头的材料，发现你能调的鸡尾酒</p>
      </div>

      {/* 今日推荐 */}
      {daily && daily.title && (
        <div
          className="card mb-6 p-4 cursor-pointer hover:shadow-md transition-shadow"
          onClick={() =>
            onJumpToDoc && daily.doc_id
              ? onJumpToDoc(daily.doc_id, daily.chunk_rowid || undefined)
              : undefined
          }
          onKeyDown={(e) => {
            // F4: a11y — role=button 需支持 Enter/Space 键盘激活
            if ((e.key === "Enter" || e.key === " ") && onJumpToDoc && daily.doc_id) {
              e.preventDefault();
              onJumpToDoc(daily.doc_id, daily.chunk_rowid || undefined);
            }
          }}
          role="button"
          tabIndex={0}
        >
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-xs px-2 py-0.5 rounded-full bg-gold-100 text-gold-700 font-medium">
              {reasonText(daily.reason)}
            </span>
            <span className="text-lg font-semibold text-ink-900">{daily.title}</span>
            {daily.base_spirit && (
              <span className="text-xs px-2 py-0.5 rounded bg-brand-50 text-brand-700">
                {daily.base_spirit}
              </span>
            )}
          </div>
        </div>
      )}

      {/* 材料选择器 */}
      <div className="card p-5 mb-4">
        <input
          className="input mb-4"
          placeholder="搜索材料... 如 金酒"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="材料搜索"
        />

        {filteredCategories.map((cat) => (
          <div key={cat.id} className="mb-3 last:mb-0 border-b border-ink-100 pb-3 last:border-b-0 last:pb-0">
            <div className="text-sm font-medium text-brand-700 mb-2">
              {cat.label}
              <span className="ml-2 text-xs text-gray-400">{cat.items.length}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {cat.items.map((name) => {
                const isSelected = !!selected[name];
                return (
                  <button
                    key={name}
                    type="button"
                    onClick={() => toggleMaterial(name, cat.id)}
                    className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                      isSelected
                        ? "bg-brand-700 text-white border-brand-700"
                        : "bg-ink-100 text-ink-600 border-ink-200 hover:border-brand-700"
                    }`}
                    aria-pressed={isSelected}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {/* 已选材料条 */}
        {selectedNames.length > 0 && (
          <div className="mt-4 p-3 rounded bg-gold-100 border-l-4 border-gold-500 flex items-center gap-2 flex-wrap">
            <span className="text-xs text-ink-600">已选：</span>
            {selectedNames.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => toggleMaterial(name, selected[name])}
                className="text-xs px-2 py-0.5 rounded-full bg-gold-500 text-ink-900 hover:bg-gold-700 hover:text-white"
              >
                {name} ×
              </button>
            ))}
            <button
              type="button"
              onClick={clearAll}
              className="ml-auto text-xs text-gray-500 hover:text-gray-700"
            >
              清空
            </button>
          </div>
        )}

        <button
          type="button"
          onClick={doMatch}
          className="btn-primary w-full mt-4"
          disabled={matching || selectedNames.length === 0}
        >
          {matching
            ? "匹配中..."
            : selectedNames.length > 0
              ? `匹配配方 →（已选 ${selectedNames.length} 种）`
              : "匹配配方 →"}
        </button>
      </div>

      {/* 错误 */}
      {error && (
        <div className="card p-4 mb-4 text-center text-red-600 text-sm">
          匹配失败：{error}
        </div>
      )}

      {/* 空状态 */}
      {!result && !error && (
        <div className="text-center py-10 text-gray-400">
          <div className="text-3xl mb-2">🍸</div>
          <p className="text-sm font-medium text-gray-600">选择材料开始</p>
          <p className="text-xs mt-1">点击上方材料 chip，或试试这些：</p>
          <div className="flex gap-2 justify-center mt-3 flex-wrap">
            <button
              type="button"
              onClick={() => quickSelect(["金酒", "味美思", "橄榄"])}
              className="text-xs px-3 py-1 rounded border border-ink-200 hover:border-brand-700"
            >
              马天尼套餐
            </button>
            <button
              type="button"
              onClick={() => quickSelect(["朗姆酒", "青柠汁", "糖浆", "薄荷叶", "苏打水"])}
              className="text-xs px-3 py-1 rounded border border-ink-200 hover:border-brand-700"
            >
              莫吉托套餐
            </button>
            <button
              type="button"
              onClick={() => quickSelect(["龙舌兰", "橙汁", "糖浆"])}
              className="text-xs px-3 py-1 rounded border border-ink-200 hover:border-brand-700"
            >
              龙舌兰日出套餐
            </button>
          </div>
        </div>
      )}

      {/* 匹配结果 */}
      {result && (
        <div>
          <MatchGroup
            title="现在就能做"
            items={result.full_match}
            emptyHint="无完整匹配，再选一些材料试试"
            variant="full"
            onJumpToDoc={onJumpToDoc}
          />
          <MatchGroup
            title="差一种就能做"
            items={result.partial_match}
            emptyHint="无差一种匹配"
            variant="partial"
            onJumpToDoc={onJumpToDoc}
          />
        </div>
      )}
    </div>
  );
}

interface MatchGroupProps {
  title: string;
  items: LabMatchItem[];
  emptyHint: string;
  variant: "full" | "partial";
  onJumpToDoc?: (docId: string, chunkRowid?: number) => void;
}

function MatchGroup({ title, items, emptyHint, variant, onJumpToDoc }: MatchGroupProps) {
  if (items.length === 0) {
    return (
      <div className="text-center py-4 text-sm text-gray-400">{emptyHint}</div>
    );
  }
  const titleColor = variant === "full" ? "text-brand-700" : "text-gold-700";
  return (
    <div className="mb-6">
      <h3 className={`text-lg font-semibold mb-3 flex items-center gap-2 ${titleColor}`}>
        {title}
        <span className="text-xs text-gray-400">({items.length})</span>
      </h3>
      <div className="space-y-3">
        {items.map((r) => (
          <RecipeMatchCard key={r.doc_id} item={r} variant={variant} onJumpToDoc={onJumpToDoc} />
        ))}
      </div>
    </div>
  );
}

interface RecipeMatchCardProps {
  item: LabMatchItem;
  variant: "full" | "partial";
  onJumpToDoc?: (docId: string, chunkRowid?: number) => void;
}

function RecipeMatchCard({ item, variant, onJumpToDoc }: RecipeMatchCardProps) {
  const isPartial = variant === "partial";
  const cardBorder = isPartial ? "border-l-4 border-l-gold-500" : "border-l-4 border-l-brand-700";
  const badgeClass = isPartial
    ? "bg-gold-100 text-gold-700"
    : "bg-brand-100 text-brand-700";
  const badgeText = isPartial
    ? `缺 ${item.missing_count ?? (item.missing?.length || 0)} 种`
    : "材料齐全";

  return (
    <div className={`card p-4 ${cardBorder}`}>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-base font-semibold text-ink-900">{item.title}</h4>
        <span className={`text-xs px-2 py-0.5 rounded-full ${badgeClass}`}>{badgeText}</span>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {(item.ingredients || []).map((ing) => (
          <span
            key={ing.name}
            className={`text-xs px-2 py-0.5 rounded ${
              ing.have
                ? "bg-brand-50 text-brand-700"
                : "bg-ink-100 text-ink-400 line-through"
            }`}
          >
            {ing.have ? "✓ " : "✗ "}
            {ing.name}
          </span>
        ))}
      </div>
      {isPartial && item.missing && item.missing.length > 0 && (
        <div className="text-xs text-gold-700 mb-2">缺：{item.missing.join("、")}</div>
      )}
      <div className="flex items-center justify-between pt-2 border-t border-dashed border-ink-200">
        {item.chunk_rowid ? (
          <button
            type="button"
            onClick={() =>
              onJumpToDoc && item.doc_id
                ? onJumpToDoc(item.doc_id, item.chunk_rowid || undefined)
                : undefined
            }
            className="text-xs text-brand-700 hover:underline"
          >
            [{item.chunk_rowid}] 查看引用
          </button>
        ) : (
          <span className="text-xs text-gray-400">无引用</span>
        )}
        {item.base_spirit && (
          <span className="text-xs text-gray-500">基酒：{item.base_spirit}</span>
        )}
      </div>
    </div>
  );
}

const MATERIAL_CATEGORIES = [
  {
    id: "base_spirit",
    label: "基酒",
    items: ["金酒", "威士忌", "朗姆酒", "龙舌兰", "白兰地", "伏特加"],
  },
  {
    id: "modifier",
    label: "辅料",
    items: ["味美思", "金巴利", "糖浆", "君度", "苦精", "汤力水", "苏打水", "可乐", "姜啤"],
  },
  {
    id: "juice",
    label: "果汁",
    items: ["柠檬汁", "青柠汁", "橙汁", "蔓越莓汁", "菠萝汁", "番茄汁"],
  },
  {
    id: "garnish",
    label: "装饰",
    items: ["橄榄", "柠檬片", "薄荷叶", "樱桃", "橙皮"],
  },
] as const;
