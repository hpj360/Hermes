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

  it("独立使用时传 role=status + aria-label 供屏幕阅读器朗读", () => {
    render(<Skeleton role="status" aria-label="正在加载标题" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "正在加载标题");
  });

  it("叶子块默认无 role（纯视觉，避免容器内重复朗读）", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelector('[role="status"]')).toBeNull();
  });

  it("SkeletonText：渲染指定行数，最后一行按比例缩短", () => {
    const { container } = render(<SkeletonText lines={4} lastLineRatio={0.5} />);
    const blocks = container.querySelectorAll(".skeleton");
    expect(blocks).toHaveLength(4);
    // 前 3 行 100%，最后一行 50%
    expect((blocks[0] as HTMLElement).style.width).toBe("100%");
    expect((blocks[3] as HTMLElement).style.width).toBe("50%");
  });

  it("SkeletonText：容器带单个 role=status（非每行一个）", () => {
    render(<SkeletonText lines={5} />);
    // 仅容器 1 个 role=status，5 行叶子无 role
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("SkeletonCard：容器带单个 role=status，内部 SkeletonText 抑制 role", () => {
    const { container } = render(<SkeletonCard />);
    const blocks = container.querySelectorAll(".skeleton");
    // 1 标题 + 2 行文本 = 3 块
    expect(blocks.length).toBeGreaterThanOrEqual(3);
    // 仅卡片容器 1 个 role=status（内部 SkeletonText announce=false）
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("SkeletonList：渲染指定数量的卡片骨架，仅列表容器 1 个 role=status", () => {
    const { container } = render(<SkeletonList count={5} />);
    const cards = container.querySelectorAll(".card");
    expect(cards).toHaveLength(5);
    // 5 张卡片均 announce=false，仅列表容器 1 个 role=status
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("SkeletonList：默认 count=3", () => {
    const { container } = render(<SkeletonList />);
    const cards = container.querySelectorAll(".card");
    expect(cards).toHaveLength(3);
  });
});
