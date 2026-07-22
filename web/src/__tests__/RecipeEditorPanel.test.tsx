/** RecipeEditorPanel 测试：表单 + 状态横幅 + 保存/提交审核 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api", () => ({
  api: {
    labRecipes: vi.fn(),
    labCreateRecipe: vi.fn(),
    labUpdateRecipe: vi.fn(),
    labSubmitRecipe: vi.fn(),
  },
}));

import { api } from "../api";
import { RecipeEditorPanel } from "../components/RecipeEditorPanel";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("RecipeEditorPanel", () => {
  it("冒烟测试：渲染不崩溃，新建模式展示草稿状态横幅", async () => {
    render(<RecipeEditorPanel />);
    expect(screen.getByText("创作新配方")).toBeInTheDocument();
    // 默认 draft 状态横幅
    expect(screen.getByText(/当前状态：草稿（draft）— 未提交/)).toBeInTheDocument();
    // 默认按钮为「创建草稿」
    expect(screen.getByRole("button", { name: "创建草稿" })).toBeInTheDocument();
  });

  it("校验：标题或正文为空时提示必填", async () => {
    const user = userEvent.setup();
    render(<RecipeEditorPanel />);
    await user.click(screen.getByRole("button", { name: "创建草稿" }));
    expect(await screen.findByText("配方名和正文为必填项。")).toBeInTheDocument();
    expect(api.labCreateRecipe).not.toHaveBeenCalled();
  });

  it("新建保存：调用 labCreateRecipe，成功后展示 doc_id", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labCreateRecipe).mockResolvedValue({
      doc_id: "doc-new-1",
      status: "draft",
      title: "夏日清风",
    });

    render(<RecipeEditorPanel />);
    await user.type(screen.getByLabelText("配方名"), "夏日清风");
    await user.type(screen.getByLabelText("配方正文"), "# 配方\n- 金酒 50ml");

    await user.click(screen.getByRole("button", { name: "创建草稿" }));

    await waitFor(() => {
      expect(api.labCreateRecipe).toHaveBeenCalledWith(expect.objectContaining({
        title: "夏日清风",
        content: "# 配方\n- 金酒 50ml",
      }));
    });
    expect(await screen.findByText(/保存成功！配方 ID：doc-new-1（草稿）/)).toBeInTheDocument();
  });

  it("材料添加：回车 / 添加按钮，去重，删除 chip", async () => {
    const user = userEvent.setup();
    render(<RecipeEditorPanel />);

    const ingInput = screen.getByLabelText("材料输入");
    await user.type(ingInput, "金酒 50ml{Enter}");
    expect(screen.getByText("金酒 50ml")).toBeInTheDocument();

    await user.type(ingInput, "柠檬汁");
    await user.click(screen.getByRole("button", { name: "添加" }));
    expect(screen.getByText("柠檬汁")).toBeInTheDocument();

    // 重复添加 → 不新增（仍只有 1 个「金酒 50ml」chip）
    await user.type(ingInput, "金酒 50ml");
    await user.click(screen.getByRole("button", { name: "添加" }));
    expect(screen.getAllByText("金酒 50ml").length).toBe(1);

    // 删除 chip
    const removeBtn = screen.getByLabelText("移除 金酒 50ml");
    await user.click(removeBtn);
    expect(screen.queryByText("金酒 50ml")).not.toBeInTheDocument();
  });

  it("编辑模式：传入 docId 时加载已有配方（含 status）", async () => {
    vi.mocked(api.labRecipes).mockResolvedValue({
      items: [
        {
          doc_id: "doc-edit-1",
          title: "已存在配方",
          source: "ugc",
          verified: false,
          hidden: false,
          status: "draft",
          season: "summer",
        },
      ],
    });

    render(<RecipeEditorPanel docId="doc-edit-1" />);
    await waitFor(() => {
      expect(api.labRecipes).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByText("编辑配方")).toBeInTheDocument();
      expect(screen.getByDisplayValue("已存在配方")).toBeInTheDocument();
      expect(screen.getByText(/当前状态：草稿（draft）— 未提交/)).toBeInTheDocument();
    });
  });

  it("编辑模式：pending 状态下控件被禁用", async () => {
    vi.mocked(api.labRecipes).mockResolvedValue({
      items: [
        {
          doc_id: "doc-pending-1",
          title: "待审核配方",
          source: "ugc",
          verified: false,
          hidden: false,
          status: "pending",
        },
      ],
    });

    render(<RecipeEditorPanel docId="doc-pending-1" />);
    await waitFor(() => {
      expect(screen.getByText(/当前状态：待审核（pending）/)).toBeInTheDocument();
    });
    // 标题输入被禁用（pending 不可编辑）
    const titleInput = screen.getByLabelText("配方名");
    expect(titleInput).toBeDisabled();
    // 保存草稿按钮被禁用
    const saveBtn = screen.getByRole("button", { name: "保存草稿" });
    expect(saveBtn).toBeDisabled();
  });

  it("保存失败：展示错误信息", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labCreateRecipe).mockRejectedValue(new Error("后端 500"));

    render(<RecipeEditorPanel />);
    await user.type(screen.getByLabelText("配方名"), "Test");
    await user.type(screen.getByLabelText("配方正文"), "Content");

    await user.click(screen.getByRole("button", { name: "创建草稿" }));

    expect(await screen.findByText(/操作失败：后端 500/)).toBeInTheDocument();
  });
});
