// F3: 骨架屏组件 — 替代各面板"加载中..."纯文字占位，提供更专业的加载感知体验。
// 设计宪法（frontend-design/SKILL.md）要求"聚焦高光时刻"，骨架屏的 shimmer 动效即加载时刻的视觉反馈。
// 纯 CSS 动效（@keyframes shimmer 定义在 index.css），无 JS 动画库依赖。
// a11y：只有独立 Skeleton 块带 role="status"；SkeletonText/SkeletonCard/SkeletonList 容器不带 role，
//       避免嵌套导致屏幕阅读器重复朗读"正在加载"。

interface SkeletonProps {
  /** 宽度，默认 100% */
  width?: string;
  /** 高度，默认 1rem */
  height?: string;
  /** 圆角，默认 var(--r-md) */
  radius?: string;
  /** 额外 className */
  className?: string;
  /** 无障碍标签，screen reader 会朗读"正在加载" */
  "aria-label"?: string;
}

/** 单块骨架占位（带 shimmer 微光扫过动效） */
export function Skeleton({
  width = "100%",
  height = "1rem",
  radius = "var(--r-md)",
  className = "",
  "aria-label": ariaLabel = "正在加载",
}: SkeletonProps) {
  return (
    <div
      className={`skeleton ${className}`}
      style={{ width, height, borderRadius: radius }}
      role="status"
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
}

/** 多行文本骨架（模拟段落加载）— 容器无 role，每行子 Skeleton 独立带 role="status" */
export function SkeletonText({
  lines = 3,
  lastLineRatio = 0.6,
  lineHeight = "0.875rem",
  gap = "0.5rem",
  className = "",
}: SkeletonTextProps) {
  return (
    <div className={className} style={{ display: "flex", flexDirection: "column", gap }}>
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

/** 卡片骨架（标题 + 2 行文本），用于列表项加载 — 容器无 role，子块独立带 role */
export function SkeletonCard() {
  return (
    <div className="card p-4">
      <Skeleton height="1.25rem" width="60%" className="mb-3" aria-label="正在加载标题" />
      <SkeletonText lines={2} lastLineRatio={0.4} />
    </div>
  );
}

/** 列表骨架（n 张卡片骨架）— 容器无 role，各卡片子块独立带 role */
export function SkeletonList({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}
