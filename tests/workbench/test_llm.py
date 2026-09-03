"""Tests for hermes.workbench.llm (LLM provider abstraction)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hermes.workbench.llm import (
    LlmApiError,
    LlmClient,
    LlmConfigError,
    LlmMessage,
    LlmResponse,
    LlmRetryPolicy,
    LlmStreamChunk,
    LlmToolCall,
    _extract_json,
    count_tokens,
    make_llm_client,
    resolve_provider,
)


# ---------------------------------------------------------------------------
# Fake Settings
# ---------------------------------------------------------------------------


class _FakeSettings:
    """Minimal stand-in for Settings with only the fields resolve_provider reads."""

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434/v1",
        openai_base_url: str | None = "https://api.openai.com/v1",
        openai_api_key: str | None = None,
        zai_base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        zai_api_key: str | None = None,
        hermes_llm_provider: str = "ollama",
        hermes_llm_model: str = "gpt-3.5-turbo",
        hermes_llm_timeout: float = 30.0,
        hermes_llm_temperature: float = 0.1,
    ) -> None:
        self.ollama_base_url = ollama_base_url
        self.openai_base_url = openai_base_url
        self.openai_api_key = openai_api_key
        self.zai_base_url = zai_base_url
        self.zai_api_key = zai_api_key
        self.hermes_llm_provider = hermes_llm_provider
        self.hermes_llm_model = hermes_llm_model
        self.hermes_llm_timeout = hermes_llm_timeout
        self.hermes_llm_temperature = hermes_llm_temperature


# ---------------------------------------------------------------------------
# resolve_provider
# ---------------------------------------------------------------------------


def test_resolve_provider_ollama_no_key() -> None:
    """ollama should resolve without an API key (local)."""
    s = _FakeSettings()
    base, key = resolve_provider("ollama", settings=s)  # type: ignore[arg-type]
    assert base == "http://localhost:11434/v1"
    assert key is None


def test_resolve_provider_openai_requires_key() -> None:
    """openai should raise LlmConfigError when no API key is set."""
    s = _FakeSettings(openai_api_key=None)
    with pytest.raises(LlmConfigError):
        resolve_provider("openai", settings=s)  # type: ignore[arg-type]


def test_resolve_provider_openai_with_key() -> None:
    """openai should resolve base_url + key when configured."""
    s = _FakeSettings(openai_api_key="sk-xxx")
    base, key = resolve_provider("openai", settings=s)  # type: ignore[arg-type]
    assert key == "sk-xxx"
    assert "openai.com" in base


def test_resolve_provider_zai_aliases() -> None:
    """zai/glm, zai, glm should all map to the Zhipu provider."""
    s = _FakeSettings(zai_api_key="zai-key")
    for alias in ("zai/glm", "zai", "glm", "ZAI", "GLM"):
        _, key = resolve_provider(alias, settings=s)  # type: ignore[arg-type]
        assert key == "zai-key"


def test_resolve_provider_unknown() -> None:
    """unknown provider name should raise LlmConfigError."""
    s = _FakeSettings()
    with pytest.raises(LlmConfigError):
        resolve_provider("nope", settings=s)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# make_llm_client
# ---------------------------------------------------------------------------


def test_make_llm_client_uses_settings_defaults() -> None:
    """make_llm_client should honor Settings.hermes_llm_provider/model."""
    s = _FakeSettings(hermes_llm_provider="ollama", hermes_llm_model="llama3")
    client = make_llm_client(settings=s)  # type: ignore[arg-type]
    assert client.model == "llama3"
    assert client.api_key is None
    assert "localhost:11434" in client.base_url


def test_make_llm_client_override_provider() -> None:
    """explicit provider/model should override Settings defaults."""
    s = _FakeSettings(
        hermes_llm_provider="ollama",
        openai_api_key="sk-xxx",
        hermes_llm_model="default-model",
    )
    client = make_llm_client(provider="openai", model="gpt-4o", settings=s)  # type: ignore[arg-type]
    assert client.model == "gpt-4o"
    assert client.api_key == "sk-xxx"


# ---------------------------------------------------------------------------
# LlmClient.chat
# ---------------------------------------------------------------------------


def _mock_urlopen_response(data: dict[str, Any]) -> Any:
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def test_llm_client_chat_parses_response() -> None:
    """chat should extract content from choices[0].message.content."""
    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="sk-xxx",
        model="gpt-4o",
    )
    fake_data = {
        "model": "gpt-4o",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }
        ],
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
        resp = client.chat([LlmMessage(role="user", content="hi")])
    assert isinstance(resp, LlmResponse)
    assert resp.content == "Hello!"
    assert resp.model == "gpt-4o"
    assert resp.finish_reason == "stop"


def test_llm_client_chat_sets_auth_header() -> None:
    """chat should send Authorization: Bearer <key> when api_key is set."""
    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="sk-secret",
        model="gpt-4o",
    )
    captured: dict[str, Any] = {}

    class FakeRequest:
        def __init__(self, url: str, data: bytes, method: str) -> None:
            captured["url"] = url
            captured["method"] = method
            captured["data"] = data
            self._headers: dict[str, str] = {}

        def add_header(self, k: str, v: str) -> None:
            captured.setdefault("headers", {})[k] = v

    fake_data = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    with patch("urllib.request.Request", FakeRequest):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
            client.chat([LlmMessage(role="user", content="hi")])
    assert captured["headers"]["Authorization"] == "Bearer sk-secret"
    assert captured["headers"]["Content-Type"].startswith("application/json")
    assert captured["url"].endswith("/chat/completions")
    assert captured["method"] == "POST"


def test_llm_client_chat_omits_auth_when_no_key() -> None:
    """chat should not send Authorization header when api_key is None (ollama)."""
    client = LlmClient(
        base_url="http://localhost:11434/v1", api_key=None, model="llama3"
    )
    captured: dict[str, Any] = {}

    class FakeRequest:
        def __init__(self, url: str, data: bytes, method: str) -> None:
            captured["url"] = url
            self._headers: dict[str, str] = {}

        def add_header(self, k: str, v: str) -> None:
            captured.setdefault("headers", {})[k] = v

    fake_data = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    with patch("urllib.request.Request", FakeRequest):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
            client.chat([LlmMessage(role="user", content="hi")])
    assert "Authorization" not in captured.get("headers", {})


def test_llm_client_chat_http_error_raises_api_error() -> None:
    """chat should raise LlmApiError on HTTP failure."""
    import urllib.error
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    err = urllib.error.HTTPError(
        url="https://api.example.com/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(LlmApiError) as exc_info:
            client.chat([LlmMessage(role="user", content="hi")])
    assert exc_info.value.status_code == 429


def test_llm_client_chat_no_choices_raises() -> None:
    """chat should raise LlmApiError when response has no choices."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response({"foo": "bar"})):
        with pytest.raises(LlmApiError):
            client.chat([LlmMessage(role="user", content="hi")])


# ---------------------------------------------------------------------------
# LlmClient.chat_json
# ---------------------------------------------------------------------------


def test_llm_client_chat_json_parses_json_content() -> None:
    """chat_json should parse JSON from the assistant content."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    fake_data = {
        "choices": [
            {"message": {"content": '{"plan": [{"skill": "deploy"}]}'}, "finish_reason": "stop"}
        ]
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
        result = client.chat_json([LlmMessage(role="user", content="plan")])
    assert result == {"plan": [{"skill": "deploy"}]}


def test_llm_client_chat_json_extracts_from_fenced_block() -> None:
    """chat_json should handle ```json fenced responses."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    fenced = "```json\n{\"achieved\": true}\n```"
    fake_data = {
        "choices": [{"message": {"content": fenced}, "finish_reason": "stop"}]
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
        result = client.chat_json([LlmMessage(role="user", content="judge")])
    assert result == {"achieved": True}


def test_llm_client_chat_json_extracts_from_prose() -> None:
    """chat_json should extract {...} from prose responses."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    prose = 'Here is the plan: {"steps": [{"skill": "test"}]} hope it helps.'
    fake_data = {
        "choices": [{"message": {"content": prose}, "finish_reason": "stop"}]
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
        result = client.chat_json([LlmMessage(role="user", content="plan")])
    assert result == {"steps": [{"skill": "test"}]}


def test_llm_client_chat_json_unparseable_raises() -> None:
    """chat_json should raise LlmApiError when content has no JSON."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    fake_data = {
        "choices": [{"message": {"content": "no json here at all"}, "finish_reason": "stop"}]
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
        with pytest.raises(LlmApiError):
            client.chat_json([LlmMessage(role="user", content="hi")])


# ---------------------------------------------------------------------------
# _extract_json helper
# ---------------------------------------------------------------------------


def test_extract_json_direct_object() -> None:
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_direct_array_wraps() -> None:
    """a bare JSON array should be wrapped as {"value": [...]}."""
    result = _extract_json('[1, 2, 3]')
    assert result == {"value": [1, 2, 3]}


def test_extract_json_fenced() -> None:
    text = "```json\n{\"x\": 2}\n```"
    assert _extract_json(text) == {"x": 2}


def test_extract_json_prose() -> None:
    text = 'result is {"y": 3} done'
    assert _extract_json(text) == {"y": 3}


def test_extract_json_invalid_raises() -> None:
    with pytest.raises(LlmApiError):
        _extract_json("no json at all")


def test_extract_json_multiple_objects_uses_first() -> None:
    """Multiple JSON objects: extract the first balanced one, not the span."""
    result = _extract_json('The result is {"a": 1} and also {"b": 2}.')
    assert result == {"a": 1}


def test_extract_json_adjacent_objects() -> None:
    result = _extract_json('{"a": 1} {"b": 2}')
    assert result == {"a": 1}


def test_retry_policy_rejects_negative_max_retries() -> None:
    with pytest.raises(ValueError):
        LlmRetryPolicy(max_retries=-1)


def test_chat_retries_on_timeout_error() -> None:
    """A bare TimeoutError (socket.timeout) should be retried, not surfaced."""
    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        retry_policy=LlmRetryPolicy(max_retries=1, base_delay=0.0, max_delay=0.0),
    )
    good = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    with patch(
        "urllib.request.urlopen",
        side_effect=[TimeoutError("timed out"), _mock_urlopen_response(good)],
    ):
        resp = client.chat([LlmMessage(role="user", content="hi")])
    assert resp.content == "ok"


# ---------------------------------------------------------------------------
# retry policy
# ---------------------------------------------------------------------------


def test_retry_policy_delay_exponential() -> None:
    p = LlmRetryPolicy(max_retries=3, base_delay=2.0, max_delay=60.0)
    assert p.delay_for(0) == 2.0
    assert p.delay_for(1) == 4.0
    assert p.delay_for(2) == 8.0
    # capped by max_delay
    assert p.delay_for(10) == 60.0


def test_chat_retries_transient_then_succeeds() -> None:
    """chat should retry a 429 then succeed on the next attempt."""
    import urllib.error

    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        retry_policy=LlmRetryPolicy(max_retries=2, base_delay=0.0, max_delay=0.0),
    )
    good = {"choices": [{"message": {"content": "recovered"}, "finish_reason": "stop"}]}
    err = urllib.error.HTTPError(
        url="x", code=429, msg="Too Many Requests", hdrs=None, fp=None
    )
    # First call raises 429, second succeeds.
    with patch(
        "urllib.request.urlopen",
        side_effect=[err, _mock_urlopen_response(good)],
    ):
        resp = client.chat([LlmMessage(role="user", content="hi")])
    assert resp.content == "recovered"


def test_chat_gives_up_after_retries() -> None:
    """chat should raise LlmApiError after retries are exhausted."""
    import urllib.error

    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        retry_policy=LlmRetryPolicy(max_retries=2, base_delay=0.0, max_delay=0.0),
    )
    err = urllib.error.HTTPError(
        url="x", code=500, msg="Server Error", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(LlmApiError) as exc_info:
            client.chat([LlmMessage(role="user", content="hi")])
    assert exc_info.value.status_code == 500


def test_chat_no_retry_when_disabled() -> None:
    """chat should not retry when max_retries=0 (default)."""
    import urllib.error

    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    err = urllib.error.HTTPError(
        url="x", code=429, msg="Too Many Requests", hdrs=None, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(LlmApiError):
            client.chat([LlmMessage(role="user", content="hi")])


# ---------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------


class _FakeStreamResp:
    """A fake file-like object yielding SSE lines for stream parsing."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self._closed = False

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        self._closed = True

    def close(self) -> None:
        self._closed = True


def _sse_lines() -> list[bytes]:
    return [
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"},\"finish_reason\":null}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"},\"finish_reason\":null}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{\"content\":\" world\"},\"finish_reason\":null}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
        b"data: [DONE]\n\n",
    ]


def test_stream_yields_content_chunks() -> None:
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    with patch("urllib.request.urlopen", return_value=_FakeStreamResp(_sse_lines())):
        chunks = list(client.stream([LlmMessage(role="user", content="hi")]))
    contents = [c.content for c in chunks]
    # Non-empty deltas plus a trailing empty chunk carrying the finish reason.
    assert contents == ["Hello", " world", ""]
    assert all(isinstance(c, LlmStreamChunk) for c in chunks)
    assert chunks[-1].finish_reason == "stop"


def test_stream_captures_finish_reason() -> None:
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    with patch("urllib.request.urlopen", return_value=_FakeStreamResp(_sse_lines())):
        chunks = list(client.stream([LlmMessage(role="user", content="hi")]))
    finish = [c.finish_reason for c in chunks if c.finish_reason]
    assert finish == ["stop"]


def test_stream_retries_transient_before_streaming() -> None:
    import urllib.error

    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        retry_policy=LlmRetryPolicy(max_retries=1, base_delay=0.0, max_delay=0.0),
    )
    err = urllib.error.HTTPError(
        url="x", code=503, msg="Unavailable", hdrs=None, fp=None
    )
    with patch(
        "urllib.request.urlopen",
        side_effect=[err, _FakeStreamResp(_sse_lines())],
    ):
        chunks = list(client.stream([LlmMessage(role="user", content="hi")]))
    assert [c.content for c in chunks] == ["Hello", " world", ""]


def test_stream_no_retry_after_partial_output() -> None:
    """P1-6：一次 yield 出 chunk 后断流，不得重试并重复输出前缀。

    模拟：第一次连接先吐出部分 chunk 再抛 URLError；若重试会返回完整 SSE
    流，导致调用方收到重复前缀（Hello world Hello world）。修复后应在断流
    处抛 LlmApiError，不再 yield 第二次结果。
    """
    import urllib.error

    client = LlmClient(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        retry_policy=LlmRetryPolicy(max_retries=2, base_delay=0.0, max_delay=0.0),
    )

    # 第一次连接 yield "Hello world" 后，下一次迭代再抛 URLError。
    class _BoomStreamResp(_FakeStreamResp):
        def __init__(self) -> None:
            super().__init__(
                [
                    b"data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"},\"finish_reason\":null}]}\n\n",
                    b"data: {\"choices\":[{\"delta\":{\"content\":\" world\"},\"finish_reason\":null}]}\n\n",
                ]
            )

        def __iter__(self):
            yield self._lines[0]
            yield self._lines[1]
            raise urllib.error.URLError("connection reset")

    seen: list[str] = []
    with patch("urllib.request.urlopen", return_value=_BoomStreamResp()):
        try:
            for chunk in client.stream([LlmMessage(role="user", content="hi")]):
                seen.append(chunk.content)
        except LlmApiError:
            pass
    # 只收到第一段的部分内容，绝无第二段重复（重试被抑制）。
    assert seen == ["Hello", " world"]



# ---------------------------------------------------------------------------
# token counting
# ---------------------------------------------------------------------------


def test_count_tokens_empty() -> None:
    assert count_tokens("") == 0


def test_count_tokens_fallback_positive() -> None:
    # tiktoken may not be installed; the fallback must be deterministic and > 0.
    n = count_tokens("hello world")
    assert isinstance(n, int) and n > 0


def test_count_tokens_consistent() -> None:
    assert count_tokens("abcd") == count_tokens("abcd")


def test_llm_client_count_tokens_method() -> None:
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    assert client.count_tokens("test") == count_tokens("test")


# ---------------------------------------------------------------------------
# function calling (tools)
# ---------------------------------------------------------------------------


def test_chat_forwards_tools_payload() -> None:
    """chat should include the tools payload in the request body."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    captured: dict[str, Any] = {}

    class FakeRequest:
        def __init__(self, url: str, data: bytes, method: str) -> None:
            captured["data"] = data
            self._headers: dict[str, str] = {}

        def add_header(self, k: str, v: str) -> None:
            pass

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]
    fake_data = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    with patch("urllib.request.Request", FakeRequest):
        with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
            client.chat([LlmMessage(role="user", content="hi")], tools=tools)
    sent = json.loads(captured["data"].decode("utf-8"))
    assert sent["tools"] == tools


def test_chat_parses_tool_calls() -> None:
    """chat should parse tool_calls from the assistant message into LlmToolCall."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    fake_data = {
        "model": "gpt-4o",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "Beijing"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
        resp = client.chat([LlmMessage(role="user", content="weather?")])
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert isinstance(call, LlmToolCall)
    assert call.id == "call_1"
    assert call.name == "get_weather"
    assert call.arguments == {"city": "Beijing"}


def test_chat_no_tool_calls_returns_empty_list() -> None:
    """chat without tool_calls should return an empty tool_calls list."""
    client = LlmClient(base_url="https://api.example.com/v1", api_key="k", model="m")
    fake_data = {"choices": [{"message": {"content": "plain"}, "finish_reason": "stop"}]}
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(fake_data)):
        resp = client.chat([LlmMessage(role="user", content="hi")])
    assert resp.tool_calls == []


def test_tool_call_from_dict_unparseable_arguments() -> None:
    """LlmToolCall.from_dict should degrade to {} on unparseable arguments."""
    call = LlmToolCall.from_dict(
        {
            "id": "call_x",
            "type": "function",
            "function": {"name": "f", "arguments": "not json"},
        }
    )
    assert call.id == "call_x"
    assert call.name == "f"
    assert call.arguments == {}


def test_tool_call_to_dict_roundtrip() -> None:
    """LlmToolCall.to_dict should emit the OpenAI wire shape."""
    call = LlmToolCall(id="call_1", name="get_weather", arguments={"city": "Beijing"})
    d = call.to_dict()
    assert d["id"] == "call_1"
    assert d["type"] == "function"
    assert d["function"]["name"] == "get_weather"
    assert json.loads(d["function"]["arguments"]) == {"city": "Beijing"}


# ---------------------------------------------------------------------------
# KV-cache prefix tracking (P0-1)
# ---------------------------------------------------------------------------


def _fake_client() -> tuple[LlmClient, dict[str, Any]]:
    client = LlmClient(base_url="http://127.0.0.1:1", api_key=None, model="m")
    captured: dict[str, Any] = {}

    def fake_post(url, payload, timeout):  # noqa: ANN001
        captured["body"] = json.loads(payload.decode("utf-8"))
        return LlmResponse(content="ok")

    client._post_once = fake_post  # type: ignore[assignment]
    return client, captured


def test_kv_cache_stats_hit_and_miss() -> None:
    """Same stable prefix twice → 1 miss + 1 hit; hit_rate = 0.5."""
    from hermes.workbench.llm import kv_cache_stats, reset_kv_cache_stats

    reset_kv_cache_stats()
    client, _ = _fake_client()
    client.chat([LlmMessage(role="user", content="a")], stable_prefix="SP")
    client.chat([LlmMessage(role="user", content="b")], stable_prefix="SP")
    stats = kv_cache_stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 1
    assert stats["total"] == 2
    assert stats["hit_rate"] == pytest.approx(0.5)
    assert stats["unique_prefixes"] == 1


def test_kv_cache_tracks_first_system_message_fallback() -> None:
    """Without stable_prefix, the leading system message is the tracked prefix."""
    from hermes.workbench.llm import kv_cache_stats, reset_kv_cache_stats

    reset_kv_cache_stats()
    client, _ = _fake_client()
    sysmsg = LlmMessage(role="system", content="AGENT DEF")
    client.chat([sysmsg, LlmMessage(role="user", content="a")])
    client.chat([sysmsg, LlmMessage(role="user", content="b")])
    stats = kv_cache_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_kv_cache_no_prefix_not_counted() -> None:
    from hermes.workbench.llm import kv_cache_stats, reset_kv_cache_stats

    reset_kv_cache_stats()
    client, _ = _fake_client()
    client.chat([LlmMessage(role="user", content="hi")])
    stats = kv_cache_stats()
    assert stats["total"] == 0
    assert stats["hit_rate"] == 0.0


def test_chat_payload_sorted_keys_deterministic() -> None:
    """Identical request content must serialize to identical bytes (P0-1)."""
    client, captured = _fake_client()
    msgs = [LlmMessage(role="user", content="hi")]
    client.chat(msgs, stable_prefix="SP")
    first_payload = captured["body"]
    # keys sorted regardless of dict insertion order
    assert list(first_payload.keys()) == sorted(first_payload.keys())


# ---------------------------------------------------------------------------
# Tool masking (P1-6)
# ---------------------------------------------------------------------------


def _tool(name: str, desc: str = "") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": desc, "parameters": {}},
    }


def test_mask_tool_schemas_masks_unauthorized() -> None:
    from hermes.workbench.llm import mask_tool_schemas

    tools = [_tool("github_get_pr", "read a pr"), _tool("github_create_pr", "write a pr")]
    masked = mask_tool_schemas(tools, ["github_get_pr"])
    # 长度与顺序保持不变（KV-cache 前缀稳定性）
    assert len(masked) == 2
    assert masked[0]["function"]["name"] == "github_get_pr"
    assert masked[0]["function"]["description"] == "read a pr"
    # 未授权工具：schema 保留但被遮蔽
    assert masked[1]["function"]["name"] == "github_create_pr"
    assert masked[1]["function"]["description"].startswith("[UNAVAILABLE")
    assert masked[1].get("masked") is True
    # 原列表不被就地修改
    assert tools[1]["function"]["description"] == "write a pr"
    assert "masked" not in tools[1]


def test_mask_tool_schemas_none_allowed_noop() -> None:
    from hermes.workbench.llm import mask_tool_schemas

    tools = [_tool("a"), _tool("b")]
    assert mask_tool_schemas(tools, None) is tools


def test_chat_forwards_masked_tools_in_payload() -> None:
    client, captured = _fake_client()
    tools = [_tool("read", "read files"), _tool("write", "write files")]
    client.chat(
        [LlmMessage(role="user", content="hi")],
        tools=tools,
        allowed_tools=["read"],
    )
    body_tools = captured["body"]["tools"]
    assert len(body_tools) == 2
    assert body_tools[1].get("masked") is True
