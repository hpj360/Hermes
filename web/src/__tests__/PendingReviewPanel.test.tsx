/** PendingReviewPanel 测试：待审核队列 + 通过/驳回操作 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api", () => ({
  api: {
    labRecipes: vi.fn(),
    labApproveRecipe: vi.fn(),
    labRejectRecipe: vi.fn(),
  },
}));

import { api } from "../api";
import { PendingReviewPanel } from "../components/PendingReviewPanel";

const PENDING_RECIPES = [
  {
    doc_id: "doc-p1",
    title: "待审核 Mojito",
    source: "ugc",
    verified: false,
    hidden: false,
    status: "pending",
  },
  {
    doc_id: "doc-p2",
    title: "待审核 Negroni",
    source: "ugc",
    verified: false,
    hidden: false,
    status: "pending",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PendingReviewPanel", () => {
  it("冒烟测试：渲染不崩溃，展示标题与计数", async () => {
    vi.mocked(api.labRecipes).mockResolvedValue({ items: [] });
    render(<PendingReviewPanel />);
    expect(screen.getByText("📨 待审核配方")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("当前无 UGC 投稿待审")).toBeInTheDocument();
    });
  });

  it("加载待审核配方后展示列表与计数", async () => {
    vi.mocked(api.labRecipes).mockResolvedValue({ items: PENDING_RECIPES });
    render(<PendingReviewPanel />);
    await waitFor(() => {
      expect(screen.getByText("待审核 Mojito")).toBeInTheDocument();
      expect(screen.getByText("待审核 Negroni")).toBeInTheDocument();
      expect(screen.getByText(/共 2 条 UGC 投稿待审/)).toBeInTheDocument();
    });
  });

  it("点击「通过」调用 labApproveRecipe 并刷新列表", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labRecipes)
      .mockResolvedValueOnce({ items: PENDING_RECIPES })
      .mockResolvedValueOnce({ items: [PENDING_RECIPES[1]] }); // 通过后只剩 1 条
    vi.mocked(api.labApproveRecipe).mockResolvedValue({ doc_id: "doc-p1", status: "ok" });

    const onResolved = vi.fn();
    render(<PendingReviewPanel onResolved={onResolved} />);
    await waitFor(() => expect(screen.getByText("待审核 Mojito")).toBeInTheDocument());

    const approveBtns = screen.getAllByText("通过");
    await user.click(approveBtns[0]);

    await waitFor(() => {
      expect(api.labApproveRecipe).toHaveBeenCalledWith("doc-p1");
    });
    await waitFor(() => {
      expect(onResolved).toHaveBeenCalled();
    });
  });

  it("点击「驳回」调用 labRejectRecipe（带 reason）", async () => {
    const user = userEvent.setup();
    // stub prompt — jsdom 默认无 prompt
    const promptSpy = vi.fn(() => "材料不合规");
    vi.stubGlobal("prompt", promptSpy);

    vi.mocked(api.labRecipes).mockResolvedValue({ items: PENDING_RECIPES });
    vi.mocked(api.labRejectRecipe).mockResolvedValue({
      doc_id: "doc-p1",
      status: "rejected",
      reason: "材料不合规",
    });

    render(<PendingReviewPanel />);
    await waitFor(() => expect(screen.getByText("待审核 Mojito")).toBeInTheDocument());

    const rejectBtns = screen.getAllByText("驳回");
    await user.click(rejectBtns[0]);

    await waitFor(() => {
      expect(api.labRejectRecipe).toHaveBeenCalledWith("doc-p1", "材料不合规");
    });

    vi.unstubAllGlobals();
  });

  it("加载失败：展示错误信息", async () => {
    vi.mocked(api.labRecipes).mockRejectedValue(new Error("服务不可用"));
    render(<PendingReviewPanel />);
    await waitFor(() => {
      expect(screen.getByText(/加载失败：服务不可用/)).toBeInTheDocument();
    });
  });
});
