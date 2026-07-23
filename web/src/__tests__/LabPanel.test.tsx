/** LabPanel 测试：今日推荐 + 材料选择 + 匹配结果展示 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock api — labDaily 在 mount 时即调用；labMatch 由测试触发
vi.mock("../api", () => ({
  api: {
    labDaily: vi.fn(),
    labMatch: vi.fn(),
  },
}));

import { api } from "../api";
import { LabPanel } from "../components/LabPanel";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LabPanel", () => {
  it("冒烟测试：渲染不崩溃，并展示空状态", async () => {
    vi.mocked(api.labDaily).mockResolvedValue({ title: null, reason: "empty" });
    render(<LabPanel />);
    expect(screen.getByText("🧪 鸡尾酒实验室")).toBeInTheDocument();
    expect(screen.getByText("选择材料开始")).toBeInTheDocument();
    // 等待 daily 加载完成
    await waitFor(() => expect(api.labDaily).toHaveBeenCalled());
  });

  it("今日推荐：labDaily 返回有效数据时展示标题与理由徽章", async () => {
    vi.mocked(api.labDaily).mockResolvedValue({
      title: "Mojito",
      reason: "season",
      doc_id: "doc-1",
      chunk_rowid: 7,
      base_spirit: "rum",
    });
    render(<LabPanel />);
    await waitFor(() => {
      expect(screen.getByText("Mojito")).toBeInTheDocument();
      expect(screen.getByText("应季推荐")).toBeInTheDocument();
    });
  });

  it("材料选择 + 匹配结果展示：点击 chip 选中 → 匹配按钮可点 → 调用 labMatch → 渲染结果", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labDaily).mockResolvedValue({ title: null, reason: "empty" });
    vi.mocked(api.labMatch).mockResolvedValue({
      full_match: [
        {
          doc_id: "doc-1",
          title: "金汤力",
          chunk_rowid: 1,
          ingredients: [
            { name: "金酒", have: true },
            { name: "汤力水", have: true },
          ],
          base_spirit: "gin",
          match_count: 2,
        },
      ],
      partial_match: [
        {
          doc_id: "doc-2",
          title: "莫吉托",
          chunk_rowid: 2,
          ingredients: [
            { name: "朗姆酒", have: false },
            { name: "青柠汁", have: true },
          ],
          missing: ["朗姆酒"],
          missing_count: 1,
        },
      ],
    });

    render(<LabPanel />);
    await waitFor(() => expect(api.labDaily).toHaveBeenCalled());

    // 初始：匹配按钮禁用
    const matchBtn = screen.getByRole("button", { name: /匹配配方/ });
    expect(matchBtn).toBeDisabled();

    // 点击「金酒」chip（在 base_spirit 分类中）
    const ginChip = screen.getByText("金酒");
    await user.click(ginChip);

    // 匹配按钮启用并显示已选数
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /已选 1 种/ })).toBeEnabled();
    });

    // 点击匹配
    await user.click(screen.getByRole("button", { name: /已选 1 种/ }));

    // labMatch 被调用
    await waitFor(() => expect(api.labMatch).toHaveBeenCalledWith(["金酒"]));

    // 渲染 full_match / partial_match
    await waitFor(() => {
      expect(screen.getByText("现在就能做")).toBeInTheDocument();
      expect(screen.getByText("金汤力")).toBeInTheDocument();
      expect(screen.getByText("材料齐全")).toBeInTheDocument();
      expect(screen.getByText("差一种就能做")).toBeInTheDocument();
      expect(screen.getByText("莫吉托")).toBeInTheDocument();
      expect(screen.getByText(/缺 1 种/)).toBeInTheDocument();
    });
  });

  it("匹配失败时展示错误信息", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labDaily).mockResolvedValue({ title: null, reason: "empty" });
    vi.mocked(api.labMatch).mockRejectedValue(new Error("后端连接失败"));

    render(<LabPanel />);
    await waitFor(() => expect(api.labDaily).toHaveBeenCalled());

    await user.click(screen.getByText("伏特加"));
    await user.click(screen.getByRole("button", { name: /已选 1 种/ }));

    await waitFor(() => {
      expect(screen.getByText(/匹配失败：后端连接失败/)).toBeInTheDocument();
    });
  });

  it("清空按钮：清空已选材料与结果", async () => {
    const user = userEvent.setup();
    vi.mocked(api.labDaily).mockResolvedValue({ title: null, reason: "empty" });
    render(<LabPanel />);
    await waitFor(() => expect(api.labDaily).toHaveBeenCalled());

    await user.click(screen.getByText("金酒"));
    expect(screen.getByRole("button", { name: /已选 1 种/ })).toBeInTheDocument();

    await user.click(screen.getByText("清空"));

    // 已选条消失，按钮恢复禁用
    expect(screen.queryByText(/已选/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^匹配配方/ })).toBeDisabled();
  });

  it("材料搜索：输入关键字过滤 chip", async () => {
    vi.mocked(api.labDaily).mockResolvedValue({ title: null, reason: "empty" });
    render(<LabPanel />);
    await waitFor(() => expect(api.labDaily).toHaveBeenCalled());

    const search = screen.getByLabelText("材料搜索");
    fireEvent.change(search, { target: { value: "金" } });

    // 「金酒」保留，「威士忌」不保留
    expect(screen.queryByText("威士忌")).not.toBeInTheDocument();
    expect(screen.getByText("金酒")).toBeInTheDocument();
  });

  it("onJumpToDoc：点击今日推荐卡片触发跳转", async () => {
    vi.mocked(api.labDaily).mockResolvedValue({
      title: "Mojito",
      reason: "hot",
      doc_id: "doc-mojito",
      chunk_rowid: 9,
    });
    const onJump = vi.fn();
    render(<LabPanel onJumpToDoc={onJump} />);
    await waitFor(() => expect(screen.getByText("Mojito")).toBeInTheDocument());

    // 点击包含「Mojito」的 daily 卡片（其 role=button）
    const dailyCard = screen.getByText("Mojito").closest('[role="button"]') as HTMLElement;
    expect(dailyCard).toBeTruthy();
    fireEvent.click(dailyCard);
    expect(onJump).toHaveBeenCalledWith("doc-mojito", 9);
  });

  it("F4 a11y：今日推荐卡片支持 Enter/Space 键盘激活", async () => {
    vi.mocked(api.labDaily).mockResolvedValue({
      title: "Negroni",
      reason: "season",
      doc_id: "doc-negroni",
      chunk_rowid: 3,
    });
    const onJump = vi.fn();
    render(<LabPanel onJumpToDoc={onJump} />);
    await waitFor(() => expect(screen.getByText("Negroni")).toBeInTheDocument());

    const dailyCard = screen.getByText("Negroni").closest('[role="button"]') as HTMLElement;
    expect(dailyCard).toBeTruthy();

    // Enter 键激活
    fireEvent.keyDown(dailyCard, { key: "Enter" });
    expect(onJump).toHaveBeenCalledWith("doc-negroni", 3);
    expect(onJump).toHaveBeenCalledTimes(1);

    // Space 键激活
    fireEvent.keyDown(dailyCard, { key: " " });
    expect(onJump).toHaveBeenCalledTimes(2);
  });

  it("F4 a11y：无 onJumpToDoc 时键盘事件不报错（防御性）", async () => {
    vi.mocked(api.labDaily).mockResolvedValue({
      title: "Daiquiri",
      reason: "random",
      doc_id: "doc-daiquiri",
      chunk_rowid: 5,
    });
    render(<LabPanel />);
    await waitFor(() => expect(screen.getByText("Daiquiri")).toBeInTheDocument());

    const dailyCard = screen.getByText("Daiquiri").closest('[role="button"]') as HTMLElement;
    // 无 onJumpToDoc 时按 Enter 不应抛错
    expect(() => fireEvent.keyDown(dailyCard, { key: "Enter" })).not.toThrow();
  });
});
