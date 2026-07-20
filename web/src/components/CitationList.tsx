import type { Citation } from "../types";

interface CitationListProps {
  citations: Citation[];
}

/** 引用列表（M1-04：含 chunk_rowid，可定位原文）。 */
export function CitationList({ citations }: CitationListProps) {
  if (!citations || citations.length === 0) {
    return (
      <div className="text-xs text-gray-400 italic mt-2">无引用</div>
    );
  }

  return (
    <div className="mt-3 space-y-2">
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        引用来源 ({citations.length})
      </div>
      <div className="space-y-1.5">
        {citations.map((c) => (
          <div
            key={`${c.doc_id}-${c.id}`}
            className="text-xs bg-gray-50 border border-gray-200 rounded p-2"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium text-brand-700">
                [{c.id}] {c.title}
              </span>
              <span className="text-gray-400">
                score: {c.score.toFixed(4)}
              </span>
            </div>
            <p className="text-gray-600 leading-relaxed line-clamp-3">
              {c.snippet}
            </p>
            <div className="text-gray-400 mt-1">
              doc_id: {c.doc_id} · chunk_rowid: {c.chunk_rowid}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
