import { useEffect, useState } from "react";
import { api } from "../api";

interface RecipeEditorPanelProps {
  /** 编辑模式：传入 docId 加载已有配方（仅 draft/rejected 可编辑）。 */
  docId?: string;
  /** 保存/提交成功后回调（让父组件切回配方治理列表）。 */
  onSaved?: () => void;
  /** 取消编辑/创建。 */
  onCancel?: () => void;
}

const BASE_SPIRITS = [
  { value: "", label: "— 请选择 —" },
  { value: "gin", label: "金酒 Gin" },
  { value: "rum", label: "朗姆酒 Rum" },
  { value: "vodka", label: "伏特加 Vodka" },
  { value: "tequila", label: "龙舌兰 Tequila" },
  { value: "whiskey", label: "威士忌 Whiskey" },
  { value: "brandy", label: "白兰地 Brandy" },
];

const DIFFICULTIES = [
  { value: "easy", label: "简单" },
  { value: "medium", label: "中等" },
  { value: "hard", label: "困难" },
];

const SEASONS = [
  { value: "", label: "不限" },
  { value: "spring", label: "春季" },
  { value: "summer", label: "夏季" },
  { value: "autumn", label: "秋季" },
  { value: "winter", label: "冬季" },
];

const STATUS_TEXT: Record<string, string> = {
  draft: "草稿（draft）— 未提交",
  pending: "待审核（pending）— 等待管理员审核",
  published: "已发布（published）— 审核通过，进入实验室",
  rejected: "已驳回（rejected）— 请修改后重新提交",
};

/** M4.3 UGC 配方编辑器：表单 + 状态横幅 + 保存草稿/提交审核。 */
export function RecipeEditorPanel({ docId, onSaved, onCancel }: RecipeEditorPanelProps) {
  const [title, setTitle] = useState("");
  const [baseSpirit, setBaseSpirit] = useState("");
  const [difficulty, setDifficulty] = useState("easy");
  const [season, setSeason] = useState("");
  const [ingredients, setIngredients] = useState<string[]>([]);
  const [ingredientInput, setIngredientInput] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState<string>("draft");
  const [currentDocId, setCurrentDocId] = useState<string | undefined>(docId);
  const [saving, setSaving] = useState(false);
  const [resultMsg, setResultMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // 编辑模式：加载已有配方元信息
  useEffect(() => {
    if (!docId) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await api.labRecipes({ limit: 500 });
        if (cancelled) return;
        const hit = (resp.items || []).find((r) => r.doc_id === docId);
        if (hit) {
          setTitle(hit.title || "");
          if (hit.season) setSeason(hit.season);
          setStatus(hit.status || "draft");
          setCurrentDocId(hit.doc_id);
        } else {
          setResultMsg({ kind: "err", text: `未找到配方 ${docId}，将作为新配方创建。` });
          setCurrentDocId(undefined);
        }
      } catch {
        if (!cancelled) {
          setResultMsg({ kind: "err", text: "加载配方元信息失败，请检查服务是否可用。" });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [docId]);

  const canEdit = status === "draft" || status === "rejected";

  const addIngredient = () => {
    const v = ingredientInput.trim();
    if (!v) return;
    if (ingredients.includes(v)) {
      setIngredientInput("");
      return;
    }
    setIngredients((arr) => [...arr, v]);
    setIngredientInput("");
  };

  const removeIngredient = (idx: number) => {
    setIngredients((arr) => arr.filter((_, i) => i !== idx));
  };

  const onIngredientKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addIngredient();
    }
  };

  const collectBody = (): { title: string; content: string; ingredients: string[]; base_spirit?: string; difficulty?: string; season?: string | null } | null => {
    const t = title.trim();
    const c = content.trim();
    if (!t || !c) {
      setResultMsg({ kind: "err", text: "配方名和正文为必填项。" });
      return null;
    }
    return {
      title: t,
      content: c,
      ingredients: ingredients.slice(),
      base_spirit: baseSpirit || undefined,
      difficulty: difficulty || undefined,
      season: season || null,
    };
  };

  const saveRecipe = async (doSubmit: boolean) => {
    const body = collectBody();
    if (!body) return;
    setSaving(true);
    setResultMsg(null);
    try {
      // 1) 创建或更新
      let savedDocId = currentDocId;
      if (currentDocId) {
        await api.labUpdateRecipe(currentDocId, {
          title: body.title,
          ingredients: body.ingredients,
          content: body.content,
          season: body.season,
        });
      } else {
        const r = await api.labCreateRecipe({
          title: body.title,
          ingredients: body.ingredients,
          content: body.content,
          base_spirit: body.base_spirit || "",
          difficulty: body.difficulty || "easy",
          season: body.season,
        });
        savedDocId = r.doc_id;
        setCurrentDocId(r.doc_id);
        setStatus("draft");
      }
      // 2) 提交审核
      if (doSubmit && savedDocId) {
        await api.labSubmitRecipe(savedDocId);
        setStatus("pending");
        setResultMsg({ kind: "ok", text: `已提交审核！配方 ID：${savedDocId}，等待管理员处理。` });
      } else {
        setResultMsg({
          kind: "ok",
          text: `保存成功！配方 ID：${savedDocId}（草稿）。`,
        });
      }
    } catch (err) {
      setResultMsg({
        kind: "err",
        text: `操作失败：${err instanceof Error ? err.message : err}`,
      });
    } finally {
      setSaving(false);
    }
  };

  const bannerClass = (() => {
    switch (status) {
      case "published": return "bg-brand-50 text-brand-700 border-brand-500";
      case "pending": return "bg-gold-100 text-gold-700 border-gold-500";
      case "rejected": return "bg-red-50 text-red-600 border-red-500";
      default: return "bg-ink-100 text-ink-600 border-ink-200";
    }
  })();

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-4">
        <div className="text-xs uppercase tracking-widest text-gold-700 mb-1">Lab · 调酒研究室</div>
        <h2 className="text-2xl font-bold text-brand-700">
          {currentDocId ? "编辑配方" : "创作新配方"}
        </h2>
      </div>

      <div className="card p-6 space-y-4">
        {/* 状态横幅 */}
        <div className={`text-sm px-3 py-2 rounded border-l-4 ${bannerClass}`}>
          当前状态：{STATUS_TEXT[status] || status}
        </div>

        {/* 标题 */}
        <div>
          <label className="block text-sm font-medium mb-1">配方名 *</label>
          <input
            type="text"
            className="input"
            placeholder="如：夏日清风"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={!canEdit || saving}
            aria-label="配方名"
          />
        </div>

        {/* 基酒 + 难度（仅创建时可设） */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">基酒</label>
            <select
              className="input"
              value={baseSpirit}
              onChange={(e) => setBaseSpirit(e.target.value)}
              disabled={!canEdit || saving || !!currentDocId}
              aria-label="基酒"
            >
              {BASE_SPIRITS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">难度</label>
            <select
              className="input"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
              disabled={!canEdit || saving || !!currentDocId}
              aria-label="难度"
            >
              {DIFFICULTIES.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* 季节 */}
        <div>
          <label className="block text-sm font-medium mb-1">季节</label>
          <select
            className="input"
            value={season}
            onChange={(e) => setSeason(e.target.value)}
            disabled={!canEdit || saving}
            aria-label="季节"
          >
            {SEASONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* 材料 */}
        <div>
          <label className="block text-sm font-medium mb-1">材料</label>
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              className="input flex-1"
              placeholder="输入材料名后回车或点击添加（如：金酒 50ml）"
              value={ingredientInput}
              onChange={(e) => setIngredientInput(e.target.value)}
              onKeyDown={onIngredientKey}
              disabled={!canEdit || saving}
              aria-label="材料输入"
            />
            <button
              type="button"
              onClick={addIngredient}
              disabled={!canEdit || saving || !ingredientInput.trim()}
              className="btn-secondary text-sm"
            >
              添加
            </button>
          </div>
          <div className="flex flex-wrap gap-2 min-h-[24px]">
            {ingredients.length === 0 ? (
              <span className="text-xs text-gray-400">未选择材料</span>
            ) : (
              ingredients.map((name, idx) => (
                <span
                  key={`${name}-${idx}`}
                  className="text-xs px-2 py-0.5 rounded-full bg-brand-50 text-brand-700 inline-flex items-center gap-1"
                >
                  {name}
                  <button
                    type="button"
                    onClick={() => removeIngredient(idx)}
                    aria-label={`移除 ${name}`}
                    className="text-brand-700 hover:text-brand-900"
                    disabled={!canEdit || saving}
                  >
                    ×
                  </button>
                </span>
              ))
            )}
          </div>
          <p className="text-xs text-gray-400 mt-1">回车快速添加；点击 chip 上的 × 移除。</p>
        </div>

        {/* 正文 */}
        <div>
          <label className="block text-sm font-medium mb-1">配方正文（Markdown）*</label>
          <textarea
            className="input min-h-[200px] font-mono text-sm"
            placeholder={"# 配方名\n\n## 配方\n- 金酒 50ml\n- 柠檬汁 20ml\n- 糖浆 10ml\n\n## 步骤\n1. 加冰摇匀\n2. 滤入冰杯\n3. 柠檬皮装饰"}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={!canEdit || saving}
            aria-label="配方正文"
          />
          <p className="text-xs text-gray-400 mt-1">
            可在正文首行使用 frontmatter 注解材料：
            <code className="font-mono bg-ink-100 px-1 rounded text-gold-700">&lt;!-- ingredients: 金酒|柠檬汁|糖浆 --&gt;</code>
          </p>
        </div>

        {/* 操作按钮 */}
        <div className="flex gap-2 flex-wrap pt-2 border-t border-ink-100">
          {currentDocId ? (
            <>
              <button
                type="button"
                onClick={() => saveRecipe(false)}
                disabled={!canEdit || saving}
                className="btn-secondary text-sm"
              >
                {saving ? "保存中..." : "保存草稿"}
              </button>
              <button
                type="button"
                onClick={() => saveRecipe(true)}
                disabled={!canEdit || saving}
                className="btn-primary text-sm"
              >
                {saving ? "提交中..." : "提交审核"}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => saveRecipe(false)}
              disabled={saving}
              className="btn-primary text-sm"
            >
              {saving ? "创建中..." : "创建草稿"}
            </button>
          )}
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              disabled={saving}
              className="text-sm px-4 py-2 rounded-md text-gray-600 hover:bg-gray-100"
            >
              取消
            </button>
          )}
          {onSaved && (status === "draft" || status === "pending") && (
            <button
              type="button"
              onClick={onSaved}
              className="text-sm px-4 py-2 rounded-md text-brand-700 hover:bg-brand-50 ml-auto"
            >
              完成
            </button>
          )}
        </div>

        {/* 结果提示 */}
        {resultMsg && (
          <div
            className={`text-sm px-3 py-2 rounded ${
              resultMsg.kind === "ok"
                ? "bg-green-50 text-green-700"
                : "bg-red-50 text-red-600"
            }`}
            role="status"
          >
            {resultMsg.text}
          </div>
        )}
      </div>
    </div>
  );
}
