import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

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
});
