// F3: 骨架屏组件 — 替代各面板"加载中..."纯文字占位，提供更专业的加载感知体验。
// 设计宪法（frontend-design/SKILL.md）要求"聚焦高光时刻"，骨架屏的 shimmer 动效即加载时刻的视觉反馈。
// 纯 CSS 动效（@keyframes shimmer 定义在 index.css），无 JS 动画库依赖。
// a11y：role="status" 只放在复合组件容器（SkeletonText/SkeletonCard/SkeletonList）上，
//       叶子 Skeleton 块纯视觉无 role —— 避免屏幕阅读器对每个 shimmer 块重复朗读"正在加载"。

interface SkeletonProps {
  /** 宽度，默认 100% */
  width?: string;
  /** 高度，默认 1rem */
  height?: string;
  /** 圆角，默认 var(--r-md) */
  radius?: string;
  /** 额外 className */
  className?: string;
  /** 无障碍角色；默认不设（叶子块纯视觉）。仅在独立使用单块骨架时传 role="status" */
  role?: "status";
  /** 无障碍标签，配合 role="status" 使用 */
  "aria-label"?: string;
}

/** 单块骨架占位（带 shimmer 微光扫过动效）。叶子块默认无 role，纯视觉。 */
export function Skeleton({
  width = "100%",
  height = "1rem",
  radius = "var(--r-md)",
  className = "",
  role,
  "aria-label": ariaLabel,
}: SkeletonProps) {
  return (
    <div
      className={`skeleton ${className}`}
      style={{ width, height, borderRadius: radius }}
      role={role}
      aria-label={ariaLabel}
    />
  );
}

interface SkeletonTextProps {
  /** 行数，默认 3 */
  lines?: number;
  /** 最后一行宽度比例（0-1），默认 0.6 */
  lastLineRatio?: number;
  /** 行高，默认 0.875rem */
  lineHeight?: string;
  /** 行间距，默认 0.5rem */
  gap?: string;
  className?: string;
  /** 是否带 role="status"（默认 true）。被 SkeletonCard 嵌套时传 false 避免重复朗读 */
  announce?: boolean;
}

/** 多行文本骨架（模拟段落加载）— 容器带 role="status"，屏幕阅读器仅朗读一次 */
export function SkeletonText({
  lines = 3,
  lastLineRatio = 0.6,
  lineHeight = "0.875rem",
  gap = "0.5rem",
  className = "",
  announce = true,
}: SkeletonTextProps) {
  return (
    <div
      className={className}
      style={{ display: "flex", flexDirection: "column", gap }}
      role={announce ? "status" : undefined}
      aria-label={announce ? "内容正在加载" : undefined}
    >
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={lineHeight}
          width={i === lines - 1 ? `${lastLineRatio * 100}%` : "100%"}
        />
      ))}
    </div>
  );
}

/** 卡片骨架（标题 + 2 行文本），用于列表项加载 — 容器带 role="status"，
 *  内部 SkeletonText 抑制 role 避免嵌套重复朗读。
 *  被 SkeletonList 嵌套时传 announce={false} 由列表容器统一朗读。 */
export function SkeletonCard({ announce = true }: { announce?: boolean }) {
  return (
    <div
      className="card p-4"
      role={announce ? "status" : undefined}
      aria-label={announce ? "卡片正在加载" : undefined}
    >
      <Skeleton height="1.25rem" width="60%" className="mb-3" />
      <SkeletonText lines={2} lastLineRatio={0.4} announce={false} />
    </div>
  );
}

/** 列表骨架（n 张卡片骨架）— 容器带 role="status"，内部卡片抑制 role */
export function SkeletonList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3" role="status" aria-label="列表正在加载">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} announce={false} />
      ))}
    </div>
  );
}
