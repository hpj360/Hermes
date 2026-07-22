import { Component, ErrorInfo, ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * React Error Boundary：捕获子组件渲染期同步错误，
 * 显示深酒红主题的降级 UI，避免整页白屏。
 *
 * 注意：Error Boundary 只能捕获渲染期、生命周期与构造函数中的同步错误，
 * 不捕获事件回调、异步代码（setTimeout/Promise）中的错误。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 控制台留痕，便于调试；不做上报以避免引入额外依赖
    console.error("[ErrorBoundary] 渲染异常：", error, info.componentStack);
  }

  private handleReload = (): void => {
    this.setState({ hasError: false, error: null });
    // 软重载以重置 React 组件状态
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;

    const message = this.state.error?.message || "未知错误";

    return (
      <div
        role="alert"
        className="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-900 to-brand-700 px-4"
      >
        <div className="max-w-md w-full bg-white rounded-lg shadow-xl overflow-hidden">
          <div className="bg-brand-700 px-6 py-4 text-white">
            <div className="flex items-center gap-3">
              <span className="text-3xl" aria-hidden="true">🍷</span>
              <div>
                <h1 className="text-lg font-bold">页面出错了</h1>
                <p className="text-sm text-brand-100">Hermes 知识库遇到了一个渲染异常</p>
              </div>
            </div>
          </div>
          <div className="p-6">
            <p className="text-gray-700 mb-4">
              抱歉，应用在渲染时发生异常。您可以尝试重新加载页面；
              若问题持续，请联系管理员并附上下方错误信息。
            </p>
            <details className="mb-4 group">
              <summary className="cursor-pointer text-sm text-brand-700 font-medium">
                查看错误详情
              </summary>
              <pre className="mt-2 p-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700 overflow-auto max-h-48 whitespace-pre-wrap break-all">
                {message}
              </pre>
            </details>
            <button
              type="button"
              onClick={this.handleReload}
              className="btn-primary w-full"
            >
              重新加载页面
            </button>
          </div>
        </div>
      </div>
    );
  }
}
