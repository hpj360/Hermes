import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock api 模块，避免 jsdom 环境下发起真实网络请求
vi.mock("../api", () => ({
  api: {
    health: vi.fn().mockResolvedValue({
      doc_count: 0,
      llm_available: false,
      llm_provider: "mock",
      embedding_available: false,
      embedding_provider: "hash",
      auth_enabled: false,
    }),
    ageGateStatus: vi.fn().mockResolvedValue({
      age_gate_enabled: false,
      message: "",
    }),
    ageGateConfirm: vi.fn().mockResolvedValue({ confirmed: true }),
    getToken: vi.fn().mockReturnValue(null),
    logout: vi.fn(),
    setToken: vi.fn(),
    // 实验室相关方法（App 在 lab/recipes tab 下不会主动调用，但子组件可能用到）
    labDaily: vi.fn().mockResolvedValue({ title: null, reason: "empty" }),
    labRecipes: vi.fn().mockResolvedValue({ items: [] }),
  },
}));

import App from "../App";

describe("App", () => {
  it("冒烟测试：能渲染不崩溃", async () => {
    // 不应抛出异常
    const { container } = render(<App />);
    expect(container).toBeTruthy();
    // App 渲染后应出现顶部栏标题（年龄门未启用，会直接放行）
    await waitFor(() => {
      expect(screen.getByText("Hermes 知识库")).toBeInTheDocument();
    });
  });

  it("侧边导航包含实验室与配方入口", async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("🧪 实验室")).toBeInTheDocument();
      expect(screen.getByText("📝 配方")).toBeInTheDocument();
    });
  });

  it("点击「🧪 实验室」切换到 LabPanel", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByText("🧪 实验室")).toBeInTheDocument());
    await user.click(screen.getByText("🧪 实验室"));
    await waitFor(() => {
      expect(screen.getByText("🧪 鸡尾酒实验室")).toBeInTheDocument();
    });
  });

  it("点击「📝 配方」切换到 RecipePanel", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(screen.getByText("📝 配方")).toBeInTheDocument());
    await user.click(screen.getByText("📝 配方"));
    await waitFor(() => {
      expect(screen.getByText("📝 配方治理")).toBeInTheDocument();
    });
  });
});
