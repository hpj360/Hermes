import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "../components/ErrorBoundary";

// React 在 ErrorBoundary 捕获错误时会向 console.error 输出堆栈，
// 测试场景下会产生噪声，这里统一静音并在每个用例后恢复。
const originalError = console.error;
afterEach(() => {
  console.error = originalError;
});

function ThrowOnRender({ message }: { message: string }): never {
  throw new Error(message);
}

describe("ErrorBoundary", () => {
  it("正常渲染：子组件无异常时原样透传", () => {
    console.error = vi.fn();
    render(
      <ErrorBoundary>
        <div data-testid="child">正常内容</div>
      </ErrorBoundary>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.getByText("正常内容")).toBeInTheDocument();
  });

  it("捕获错误：子组件渲染抛错时显示降级 UI", () => {
    console.error = vi.fn();
    render(
      <ErrorBoundary>
        <ThrowOnRender message="模拟渲染失败" />
      </ErrorBoundary>
    );
    // 降级 UI 应可见
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("页面出错了")).toBeInTheDocument();
    // 错误详情可展开查看
    expect(screen.getByText("查看错误详情")).toBeInTheDocument();
    // 重载按钮存在
    expect(screen.getByText("重新加载页面")).toBeInTheDocument();
  });

  it("错误详情包含原始错误信息", () => {
    console.error = vi.fn();
    render(
      <ErrorBoundary>
        <ThrowOnRender message="特定错误文本 XYZ" />
      </ErrorBoundary>
    );
    expect(screen.getByText("特定错误文本 XYZ")).toBeInTheDocument();
  });
});
