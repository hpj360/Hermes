import type { Citation } from "../types";

interface CitationListProps {
  citations: Citation[];
  onJumpToDoc?: (docId: string, chunkRowid?: number) => void;
}

/**
 * 引用列表（M1-04：含 chunk_rowid；M2-04：点击跳转文档详情）。
 *
 * h6 设计重构：作为 JTBD 核心（引用式问答溯源），这里是用户会记住的视觉亮点
 * （frontend-design/SKILL.md：「差异化亮点 + 破格构图 + 氛围背景」）。
 * 金箔质感的来源编号 + 杂志式分栏 + 戏剧化阴影 hover，把"溯源可信感"做出来。
 */
export function CitationList({ citations, onJumpToDoc }: CitationListProps) {
  if (!citations || citations.length === 0) {
    return (
      <div
        className="text-xs italic mt-3"
        style={{ color: "var(--ink-400)", fontFamily: "var(--font-sans)" }}
      >
        无引用
      </div>
    );
  }

  return (
    <div className="mt-4">
      {/* 杂志式分栏标题：金箔分隔线 + 大写 tracking */}
      <div className="flex items-center gap-2 mb-2.5">
        <span
          className="text-[0.7rem] font-semibold uppercase tracking-[0.18em]"
          style={{ color: "var(--gold-700)", fontFamily: "var(--font-sans)" }}
        >
          来源溯源
        </span>
        <span
          className="text-[0.7rem] font-medium"
          style={{ color: "var(--ink-400)", fontFamily: "var(--font-mono)" }}
        >
          {citations.length}
        </span>
        <span
          className="flex-1 h-px"
          style={{ background: "var(--gold-foil)" }}
        />
      </div>

      <div className="space-y-2">
        {citations.map((c) => {
          const canJump = onJumpToDoc && c.doc_id;
          return (
            <div
              key={`${c.doc_id}-${c.id}`}
              onClick={() => canJump && onJumpToDoc!(c.doc_id, c.chunk_rowid || undefined)}
              title={canJump ? "点击查看原文" : undefined}
              className="group relative overflow-hidden rounded-md transition-all"
              style={{
                background: "var(--ink-50)",
                border: "1px solid var(--ink-200)",
                cursor: canJump ? "pointer" : "default",
              }}
            >
              {/* 左侧金箔竖条（破格元素：略微超出顶边，强化"被引用"的物理感） */}
              <span
                className="absolute left-0 top-0 bottom-0 w-[3px]"
                style={{ background: "var(--gold-foil)" }}
              />
              {/* hover 金色光晕（聚焦高光时刻，非散落微交互） */}
              {canJump && (
                <span
                  className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
                  style={{ boxShadow: "var(--shadow-gold)" }}
                />
              )}

              <div className="pl-4 pr-3 py-2.5 relative">
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  {/* 金箔来源编号 + 衬线标题 */}
                  <div className="flex items-baseline gap-2 min-w-0">
                    <span
                      className="text-gold-foil font-bold leading-none flex-shrink-0"
                      style={{
                        fontFamily: "var(--font-serif)",
                        fontSize: "1.05rem",
                      }}
                    >
                      [{c.id}]
                    </span>
                    <span
                      className="font-semibold truncate"
                      style={{
                        color: "var(--ink-900)",
                        fontFamily: "var(--font-serif)",
                        fontSize: "0.92rem",
                      }}
                    >
                      {c.title}
                    </span>
                  </div>
                  <span
                    className="text-[0.65rem] flex-shrink-0"
                    style={{
                      color: "var(--ink-400)",
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {c.score.toFixed(4)}
                  </span>
                </div>

                <p
                  className="leading-relaxed line-clamp-3"
                  style={{
                    color: "var(--ink-600)",
                    fontFamily: "var(--font-sans)",
                    fontSize: "0.8rem",
                  }}
                >
                  {c.snippet}
                </p>

                <div
                  className="flex items-center gap-2 mt-1.5"
                  style={{
                    color: "var(--ink-400)",
                    fontFamily: "var(--font-mono)",
                    fontSize: "0.62rem",
                  }}
                >
                  <span>doc: {c.doc_id}</span>
                  <span style={{ color: "var(--gold-300)" }}>·</span>
                  <span>chunk: {c.chunk_rowid}</span>
                  {canJump && (
                    <span
                      className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity font-medium"
                      style={{ color: "var(--brand-700)", fontFamily: "var(--font-sans)" }}
                    >
                      查看原文 →
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
