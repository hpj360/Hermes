/** RecipePanel 测试：筛选 + 卡片操作（verify / hide） */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock api — labRecipes（含 status=pending 子调用）/ labVerifyRecipe / labHideRecipe
vi.mock("../api", () => ({
  api: {
    labRecipes: vi.fn(),
    labVerifyRecipe: vi.fn(),
    labHideRecipe: vi.fn(),
    labApproveRecipe: vi.fn(),
    labRejectRecipe: vi.fn(),
  },
}));

import { api } from "../api";
import { RecipePanel } from "../components/RecipePanel";

const SAMPLE_RECIPES = [
  {
    doc_id: "doc-a",
    title: "Mojito",
    source: "ugc",
    verified: false,
    hidden: false,
    status: "published",
    season: "summer",
  },
  {
    doc_id: "doc-b",
    title: "Negroni",
    source: "iba_dataset",
    verified: true,
    hidden: false,
    status: "published",
  },
  {
    doc_id: "doc-c",
    title: "隐藏配方",
    source: "local",
    verified: false,
    hidden: true,
    status: "published",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  // 默认 labRecipes 返回完整列表；待审核子调用返回空（PendingReviewPanel）
  vi.mocked(api.labRecipes).mockImplementation(async (params) => {
    if (params?.status === "pending") return { items: [] };
    return { items: SAMPLE_RECIPES };
  });
});

describe("RecipePanel", () => {
  it("冒烟测试：渲染不崩溃，展示标题与配方卡片", async () => {
    render(<RecipePanel />);
    expect(screen.getByText("📝 配方治理")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Mojito")).toBeInTheDocument();
      expect(screen.getByText("Negroni")).toBeInTheDocument();
    });
  });

  it("筛选 source=ugc：仅展示 UGC 配方", async () => {
    const user = userEvent.setup();
    render(<RecipePanel />);
    await waitFor(() => expect(screen.getByText("Mojito")).toBeInTheDocument());

    // 切换 source 筛选
    const sourceSelect = screen.getByLabelText("来源筛选");
    await user.selectOptions(sourceSelect, "ugc");

    // labRecipes 收到 source=ugc 调用
    await waitFor(() => {
      const calls = vi.mocked(api.labRecipes).mock.calls;
      const lastCall = calls[calls.length - 1];
      expect(lastCall?.[0]?.source).toBe("ugc");
    });
  });

  it("搜索框：按标题过滤展示", async () => {
    render(<RecipePanel />);
    await waitFor(() => expect(screen.getByText("Mojito")).toBeInTheDocument());

    const search = screen.getByLabelText("配方搜索");
    fireEvent.change(search, { target: { value: "Mojito" } });

    expect(screen.getByText("Mojito")).toBeInTheDocument();
    expect(screen.queryByText("Negroni")).not.toBeInTheDocument();
  });

  it("卡片操作：点击「审核通过」调用 labVerifyRecipe 并刷新列表", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labVerifyRecipe).mockResolvedValue({ doc_id: "doc-a", status: "ok" });

    render(<RecipePanel />);
    await waitFor(() => expect(screen.getByText("Mojito")).toBeInTheDocument());

    // Mojito 卡片的「审核通过」按钮（doc-c 也有此按钮，需 scope 到 doc-a）
    const mojitoCard = document.querySelector('[data-doc-id="doc-a"]') as HTMLElement;
    const verifyBtn = within(mojitoCard).getByText("审核通过");
    await user.click(verifyBtn);

    await waitFor(() => {
      expect(api.labVerifyRecipe).toHaveBeenCalledWith("doc-a");
    });
    // 验证后再次调用 labRecipes 刷新
    await waitFor(() => {
      const calls = vi.mocked(api.labRecipes).mock.calls;
      expect(calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("卡片操作：点击「隐藏」调用 labHideRecipe(true)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labHideRecipe).mockResolvedValue({ doc_id: "doc-a", hidden: true });

    render(<RecipePanel />);
    await waitFor(() => expect(screen.getByText("Mojito")).toBeInTheDocument());

    // Mojito 卡片的「隐藏」按钮（doc-b 也有此按钮，需 scope 到 doc-a）
    const mojitoCard = document.querySelector('[data-doc-id="doc-a"]') as HTMLElement;
    const hideBtn = within(mojitoCard).getByText("隐藏");
    await user.click(hideBtn);

    await waitFor(() => {
      expect(api.labHideRecipe).toHaveBeenCalledWith("doc-a", true);
    });
  });

  it("已隐藏配方：显示「取消隐藏」按钮，点击调用 labHideRecipe(false)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labHideRecipe).mockResolvedValue({ doc_id: "doc-c", hidden: false });

    render(<RecipePanel />);
    await waitFor(() => expect(screen.getByText("隐藏配方")).toBeInTheDocument());

    // 「隐藏配方」卡片的「取消隐藏」按钮
    const unhideBtn = screen.getByText("取消隐藏");
    await user.click(unhideBtn);

    await waitFor(() => {
      expect(api.labHideRecipe).toHaveBeenCalledWith("doc-c", false);
    });
  });

  it("加载失败：展示错误信息", async () => {
    // PendingReviewPanel 与 RecipePanel 都会调用 labRecipes，二者都会失败 → 用 findAllByText
    vi.mocked(api.labRecipes).mockRejectedValue(new Error("数据库连接失败"));

    render(<RecipePanel />);
    await waitFor(() => {
      const errs = screen.getAllByText(/加载失败：数据库连接失败/);
      expect(errs.length).toBeGreaterThan(0);
    });
  });

  it("onCreateRecipe 回调：点击「+ 创作配方」触发", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    render(<RecipePanel onCreateRecipe={onCreate} />);
    await waitFor(() => expect(screen.getByText("Mojito")).toBeInTheDocument());

    await user.click(screen.getByText("+ 创作配方"));
    expect(onCreate).toHaveBeenCalled();
  });
});
