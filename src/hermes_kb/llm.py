"""LLM 客户端：Provider 抽象 + 流式输出。

支持的 Provider：
- mock：从检索片段拼装（默认，无 Key 时降级）
- openai：OpenAI 兼容协议（OpenAI / Moonshot / Novita / ModelScope 等）
- zhipu：智谱 BigModel 兼容协议（GLM-4 系列，OpenAI 兼容 SSE 流）

流式接口 chat_stream() 为 async generator，yield 增量 token。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from hermes_kb.config import get_settings


@dataclass
class LLMResponse:
    content: str
    model: str


class LLMBackend(Protocol):
    """LLM 后端协议。"""

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse: ...

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]: ...


# ---------------------------------------------------------------------------
# Mock 后端
# ---------------------------------------------------------------------------
class MockLLMBackend:
    """从检索片段拼装答案（无 Key 时降级）。"""

    MODEL_NAME = "mock-llm"

    def __init__(self) -> None:
        self.settings = get_settings()

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        content = self._compose(messages)
        return LLMResponse(content=content, model=self.MODEL_NAME)

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        content = self._compose(messages)
        # 按段落流式 yield，模拟打字效果
        paragraphs = content.split("\n")
        for para in paragraphs:
            # 每段按字符切片
            for i in range(0, len(para), 6):
                yield para[i : i + 6]
            yield "\n"

    def _compose(self, messages: list[dict[str, str]]) -> str:
        sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        pattern = re.compile(
            r'<untrusted_retrieval[^>]*>\s*\[(\d+)\]\s*(.*?)\s*</untrusted_retrieval>',
            re.DOTALL,
        )
        matches = pattern.findall(sys_msg)
        if not matches:
            return "知识库中暂无相关信息，请尝试导入相关文档后再问。"
        parts = ["根据知识库检索结果：\n"]
        for idx, text in matches[:3]:
            text = text.strip()
            if len(text) > 400:
                text = text[:400] + "…"
            parts.append(f"\n[{idx}] {text}\n")
        return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# OpenAI 兼容后端
# ---------------------------------------------------------------------------
class OpenAICompatBackend:
    """OpenAI 兼容后端（含智谱等遵循 OpenAI 协议的服务）。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        import httpx

        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 800,
            "stream": False,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return LLMResponse(content=content, model=self.settings.llm_model)

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """流式调用 OpenAI 兼容接口。

        解析 SSE `data: {...}` 行，yield content delta。
        """
        import httpx

        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        body = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 800,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            return
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content


# ---------------------------------------------------------------------------
# 客户端入口
# ---------------------------------------------------------------------------
class LLMClient:
    """LLM 客户端：根据配置选择后端。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._backend: LLMBackend = self._select_backend()

    def _select_backend(self) -> LLMBackend:
        provider = self.settings.llm_provider.lower()
        if provider == "mock":
            return MockLLMBackend()
        if self.settings.llm_available:
            return OpenAICompatBackend()
        return MockLLMBackend()

    @property
    def backend_name(self) -> str:
        return self._backend.__class__.__name__

    def chat(self, messages: list[dict[str, str]]) -> LLMResponse:
        try:
            return self._backend.chat(messages)
        except Exception:
            # 任何异常都降级 Mock，保证可用性
            return MockLLMBackend().chat(messages)

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """流式问答。

        真实后端异常时降级 Mock 流式。
        """
        try:
            async for chunk in self._backend.chat_stream(messages):
                yield chunk
        except Exception:
            # 降级 Mock 流式
            async for chunk in MockLLMBackend().chat_stream(messages):
                yield chunk
