import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { CitationList } from "./CitationList";
import type { Citation, SSEEvent } from "../types";

interface ChatPanelProps {
  refreshDocs: () => void;
  onJumpToDoc?: (docId: string, chunkRowid?: number) => void;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  rejected?: boolean;
  lowConfidence?: boolean;
  modelUsed?: string;
  latencyMs?: number;
  streaming?: boolean;
}

/** 问答面板（M1-03：SSE 流式生成）。 */
export function ChatPanel({ refreshDocs, onJumpToDoc }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // P2-4: 组件卸载时中止进行中的 SSE 流，避免 LLM token 泄漏与卸载后 setState
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const send = async () => {
    const query = input.trim();
    if (!query || loading) return;

    setInput("");
    setLoading(true);
    const userMsg: Message = { role: "user", content: query };
    const asstMsg: Message = {
      role: "assistant",
      content: "",
      streaming: true,
      citations: [],
    };
    setMessages((m) => [...m, userMsg, asstMsg]);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await api.askStream(
        query,
        undefined,
        (evt: SSEEvent) => {
          if (evt.type === "meta") {
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              copy[copy.length - 1] = {
                ...last,
                citations: evt.citations,
                rejected: evt.rejected,
                lowConfidence: evt.low_confidence,
                modelUsed: evt.model_used,
              };
              return copy;
            });
          } else if (evt.type === "delta") {
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              copy[copy.length - 1] = {
                ...last,
                content: last.content + evt.content,
              };
              return copy;
            });
          } else if (evt.type === "done") {
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              copy[copy.length - 1] = {
                ...last,
                streaming: false,
                latencyMs: evt.latency_ms,
              };
              return copy;
            });
          } else if (evt.type === "error") {
            setMessages((m) => {
              const copy = [...m];
              const last = copy[copy.length - 1];
              copy[copy.length - 1] = {
                ...last,
                content: `生成失败：${evt.message}`,
                streaming: false,
              };
              return copy;
            });
          }
        },
        ctrl.signal
      );
    } catch (err) {
      setMessages((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        copy[copy.length - 1] = {
          ...last,
          content:
            err instanceof Error && err.name === "AbortError"
              ? "（已取消）"
              : `请求失败：${err instanceof Error ? err.message : String(err)}`,
          streaming: false,
        };
        return copy;
      });
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  const cancel = () => {
    abortRef.current?.abort();
  };

  const seed = async () => {
    setLoading(true);
    try {
      const r = await api.seed();
      alert(`种子导入完成：成功 ${r.seeded} 篇，失败 ${r.failed} 篇`);
      refreshDocs();
    } catch (err) {
      alert(`种子导入失败：${err instanceof Error ? err.message : err}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 工具栏 */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-gray-50">
        <h2 className="text-sm font-semibold text-gray-700">问答</h2>
        <button
          onClick={seed}
          className="text-xs text-brand-700 hover:text-brand-500"
          disabled={loading}
        >
          导入种子知识
        </button>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 mt-12">
            <div className="text-4xl mb-2">🍷</div>
            <p className="text-sm">向 Hermes 知识库提问吧</p>
            <p className="text-xs mt-1">试试："金酒的核心风味是什么？"</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-3xl rounded-lg px-4 py-3 ${
                m.role === "user"
                  ? "bg-brand-600 text-white"
                  : "bg-white border border-gray-200"
              }`}
            >
              {m.role === "user" ? (
                <p className="whitespace-pre-wrap">{m.content}</p>
              ) : (
                <>
                  {m.rejected && (
                    <div className="text-xs bg-red-50 text-red-700 px-2 py-1 rounded mb-2">
                      已拒绝：检测到越狱尝试
                    </div>
                  )}
                  {m.lowConfidence && (
                    <div className="text-xs bg-yellow-50 text-yellow-700 px-2 py-1 rounded mb-2">
                      低置信度：知识库中暂无足够相关信息
                    </div>
                  )}
                  <p className="whitespace-pre-wrap text-gray-800">
                    {m.content || (m.streaming ? "生成中..." : "")}
                    {m.streaming && (
                      <span className="inline-block w-2 h-4 ml-1 bg-brand-500 animate-pulse" />
                    )}
                  </p>
                  {m.citations && m.citations.length > 0 && (
                    <CitationList citations={m.citations} onJumpToDoc={onJumpToDoc} />
                  )}
                  {m.latencyMs !== undefined && !m.streaming && (
                    <div className="text-xs text-gray-400 mt-2">
                      {m.modelUsed} · {m.latencyMs}ms
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* 输入区 */}
      <div className="border-t p-4 bg-white">
        <div className="flex gap-2">
          <textarea
            className="input flex-1 resize-none"
            rows={2}
            placeholder="输入问题，回车发送，Shift+回车换行"
            aria-label="问题输入框"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            disabled={loading}
          />
          {loading ? (
            <button onClick={cancel} className="btn-danger">
              取消
            </button>
          ) : (
            <button
              onClick={send}
              className="btn-primary"
              disabled={!input.trim()}
            >
              发送
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
