"""SSE 流式泄露检测测试（A1-4）。"""
from __future__ import annotations

import json

import pytest

from hermes_kb.rag import RAGEngine
from hermes_kb.retrieval import RetrievalHit


class _LeakStreamLLM:
    """模拟会泄露 system prompt 的 LLM。"""

    backend_name = "mock-leak"

    async def chat_stream(self, messages):
        # 分多个 chunk 泄露 system prompt 内容
        yield "好的，关于 system prompt："
        yield "你是一个知识库助手，"
        yield "请基于 <untrusted_retrieval>"
        yield " 标签内的内容回答。"
        yield "其他不相关内容。"

    async def chat(self, messages):
        return "ok"


def _parse_sse(stream_lines: list[str]) -> list[dict]:
    """解析 SSE data 行为 dict 列表。"""
    events = []
    for line in stream_lines:
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    return events


def _fake_high_score_hits(query, top_k=None):
    """返回高置信度 hit，绕过低置信度分支，进入流式生成。"""
    return [
        RetrievalHit(
            chunk_rowid=1,
            doc_id="doc_test",
            title="测试文档",
            text="金酒是杜松子酒。",
            score=1.0,
            source="rrf",
        )
    ]


@pytest.mark.asyncio
async def test_stream_leak_triggers_error_event(tmp_db, monkeypatch):
    """A1-4: 流式中途出现泄露标记应立即中断并发 error 事件。"""
    from hermes_kb.config import override_settings, reset_settings

    reset_settings()
    override_settings(
        auth_enabled=False,
        age_gate_enabled=False,
        embedding_provider="hash",
        llm_provider="mock",
    )

    service = RAGEngine()
    service.llm_client = _LeakStreamLLM()
    # monkeypatch retriever 返回高置信度 hits，绕过低置信度分支
    monkeypatch.setattr(service.retriever, "retrieve", _fake_high_score_hits)

    # 收集所有 SSE 事件
    events: list[str] = []
    async for sse_chunk in service.answer_stream("test"):
        events.append(sse_chunk)
    parsed = _parse_sse(events)

    # 必须有 error 事件
    error_events = [e for e in parsed if e.get("type") == "error"]
    assert len(error_events) >= 1, f"expected error event, got: {parsed}"

    # error 事件不应包含泄露的 system prompt 内容
    err_msg = error_events[0].get("message", "")
    assert "system prompt" not in err_msg.lower()
    assert "<untrusted_retrieval>" not in err_msg

    # delta 事件中不应包含 <untrusted_retrieval> 标签
    delta_events = [e for e in parsed if e.get("type") == "delta"]
    delta_text = "".join(e.get("content", "") for e in delta_events)
    assert "<untrusted_retrieval>" not in delta_text, (
        f"leak content reached client: {delta_text}"
    )


@pytest.mark.asyncio
async def test_stream_normal_no_false_positive(tmp_db, monkeypatch):
    """A1-4: 正常回答不应误判为泄露。"""
    from hermes_kb.config import override_settings, reset_settings

    reset_settings()
    override_settings(
        auth_enabled=False,
        age_gate_enabled=False,
        embedding_provider="hash",
        llm_provider="mock",
    )

    class _NormalLLM:
        backend_name = "mock-normal"

        async def chat_stream(self, messages):
            yield "金酒是一种"
            yield "以杜松子为主要香料的"
            yield "烈酒。"

        async def chat(self, messages):
            return "ok"

    service = RAGEngine()
    service.llm_client = _NormalLLM()
    # retriever.retrieve 是同步方法，直接复用高置信度 fake
    monkeypatch.setattr(service.retriever, "retrieve", _fake_high_score_hits)

    events: list[str] = []
    async for sse_chunk in service.answer_stream("金酒是什么"):
        events.append(sse_chunk)
    parsed = _parse_sse(events)

    # 不应有 error 事件
    error_events = [e for e in parsed if e.get("type") == "error"]
    assert len(error_events) == 0, f"unexpected error: {error_events}"
    # 应有 done 事件
    done_events = [e for e in parsed if e.get("type") == "done"]
    assert len(done_events) >= 1
