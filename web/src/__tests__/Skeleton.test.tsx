/** F3: Skeleton 骨架屏组件测试 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Skeleton, SkeletonText, SkeletonCard, SkeletonList } from "../components/Skeleton";

describe("Skeleton", () => {
  it("渲染单块骨架，应用自定义宽高样式", () => {
    const { container } = render(<Skeleton width="200px" height="2rem" />);
    const el = container.querySelector(".skeleton") as HTMLElement;
    expect(el).toBeTruthy();
    expect(el.style.width).toBe("200px");
    expect(el.style.height).toBe("2rem");
  });

  it("默认 role=status + aria-label 供屏幕阅读器朗读", () => {
    render(<Skeleton aria-label="正在加载标题" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "正在加载标题");
  });

  it("SkeletonText：渲染指定行数，最后一行按比例缩短", () => {
    const { container } = render(<SkeletonText lines={4} lastLineRatio={0.5} />);
    const blocks = container.querySelectorAll(".skeleton");
    expect(blocks).toHaveLength(4);
    // 前 3 行 100%，最后一行 50%
    expect((blocks[0] as HTMLElement).style.width).toBe("100%");
    expect((blocks[3] as HTMLElement).style.width).toBe("50%");
  });

  it("SkeletonCard：包含标题占位 + 文本占位", () => {
    const { container } = render(<SkeletonCard />);
    const blocks = container.querySelectorAll(".skeleton");
    // 1 标题 + 2 行文本 = 3 块
    expect(blocks.length).toBeGreaterThanOrEqual(3);
    // 多个子块各带 role=status
    expect(screen.getAllByRole("status").length).toBeGreaterThanOrEqual(1);
  });

  it("SkeletonList：渲染指定数量的卡片骨架", () => {
    const { container } = render(<SkeletonList count={5} />);
    const cards = container.querySelectorAll(".card");
    expect(cards).toHaveLength(5);
  });

  it("SkeletonList：默认 count=3", () => {
    const { container } = render(<SkeletonList />);
    const cards = container.querySelectorAll(".card");
    expect(cards).toHaveLength(3);
  });
});
