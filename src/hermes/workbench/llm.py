"""LLM provider abstraction for the Workbench agent runtime.

A thin, dependency-free client for OpenAI-compatible Chat Completions APIs.
Uses only :mod:`urllib` so the project keeps its zero-external-dependency
constraint (pydantic / pydantic-settings / python-dotenv only).

Supported providers (all expose ``/chat/completions``):
    * zai/glm  — Zhipu AI (https://open.bigmodel.cn/api/paas/v4)
    * ollama   — local (http://localhost:11434/v1), no API key required
    * openai   — official or compatible
    * openrouter, moonshot, modelscope, novita — OpenAI-compatible

Public surface:
    * :class:`LlmMessage`  — role/content message
    * :class:`LlmResponse` — normalized response
    * :class:`LlmStreamChunk` — a single token/delta chunk from stream()
    * :class:`LlmClient`   — chat() / chat_json() / stream() / count_tokens()
    * :class:`LlmRetryPolicy` — exponential backoff retry configuration
    * :func:`make_llm_client` — factory wired to Settings
    * :func:`resolve_provider` — map provider name → (base_url, api_key)
    * :func:`count_tokens` — approximate token count (tiktoken if available)

Error hierarchy:
    LlmError
    ├── LlmConfigError  — missing credentials / unknown provider
    └── LlmApiError     — HTTP failure or non-OK JSON payload
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from hermes.config import Settings, get_settings

logger = logging.getLogger("hermes.workbench.llm")

__all__ = [
    "LlmApiError",
    "LlmClient",
    "LlmConfigError",
    "LlmError",
    "LlmMessage",
    "LlmResponse",
    "LlmRetryPolicy",
    "LlmStreamChunk",
    "count_tokens",
    "make_llm_client",
    "resolve_provider",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LlmError(Exception):
    """Base error for the LLM layer."""


class LlmConfigError(LlmError):
    """Raised when a provider cannot be used (missing key/unknown name)."""


class LlmApiError(LlmError):
    """Raised when the provider HTTP call fails or returns a non-OK payload."""

    def __init__(self, message: str, status_code: int = -1) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LlmMessage:
    """A single chat message."""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LlmResponse:
    """Normalized LLM response."""

    content: str
    model: str = ""
    finish_reason: str = ""
    tool_calls: list[LlmToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LlmToolCall:
    """A single tool/function call requested by the model.

    Mirrors the OpenAI ``tool_calls`` shape: an id, a function name, and a
    JSON-arguments blob (parsed into a dict). ``arguments`` may be ``{}`` when
    the model returns no arguments or unparseable JSON.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LlmToolCall":
        """Build from an OpenAI ``tool_calls`` item (handles string or dict args).

        Accepts both the OpenAI wire shape (``{"function": {"name", "arguments"}}``)
        and a flattened ``{"name", "arguments"}`` form used by some providers.
        """
        fn = data.get("function") or {}
        name = fn.get("name") or data.get("name") or ""
        raw_args = fn.get("arguments", data.get("arguments"))
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        return cls(
            id=str(data.get("id", "")),
            name=str(name),
            arguments=args,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize back to the OpenAI wire format."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass
class LlmStreamChunk:
    """A single delta chunk from a streaming chat completion."""

    content: str
    finish_reason: str = ""
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class LlmRetryPolicy:
    """Exponential backoff retry configuration for LLM HTTP calls.

    Retries are triggered on transient failures: HTTP 429 (rate limit),
    5xx (server error), or network errors (``URLError``). ``max_retries=0``
    disables retry (the default, preserving prior behavior).
    """

    max_retries: int = 0
    base_delay: float = 2.0
    max_delay: float = 60.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")

    def delay_for(self, attempt: int) -> float:
        """Backoff delay in seconds for *attempt* (0-indexed)."""
        return min(float(self.base_delay * (2 ** attempt)), self.max_delay)


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def resolve_provider(
    name: str, settings: Settings | None = None
) -> tuple[str, str | None]:
    """Map a provider name to ``(base_url, api_key)``.

    For local providers (e.g. ``ollama``) the api_key may be ``None``.

    Raises :class:`LlmConfigError` when the provider is unknown or a remote
    provider has no API key configured.
    """
    s = settings or get_settings()
    name = (name or "").strip().lower()

    # (settings_attr_base_url, settings_attr_api_key)
    table: dict[str, tuple[str, str | None]] = {
        "ollama": ("ollama_base_url", None),
        "openai": ("openai_base_url", "openai_api_key"),
        "openrouter": ("openrouter_base_url", "openrouter_api_key"),
        "moonshot": ("moonshot_base_url", "moonshot_api_key"),
        "modelscope": ("modelscope_base_url", "modelscope_api_key"),
        "novita": ("novita_base_url", "novita_api_key"),
        "zai/glm": ("zai_base_url", "zai_api_key"),
        "zai": ("zai_base_url", "zai_api_key"),
        "glm": ("zai_base_url", "zai_api_key"),
    }
    if name not in table:
        raise LlmConfigError(f"unknown LLM provider: {name!r}")
    base_attr, key_attr = table[name]
    base_url = getattr(s, base_attr)
    api_key = getattr(s, key_attr) if key_attr else None
    if key_attr and not api_key:
        raise LlmConfigError(
            f"provider {name!r} requires an API key (env var not set)"
        )
    return base_url, api_key


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LlmClient:
    """OpenAI-compatible Chat Completions client (stdlib only)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 60.0,
        temperature: float = 0.2,
        retry_policy: LlmRetryPolicy | None = None,
    ) -> None:
        # Normalize: ensure base_url has no trailing slash so we can append
        # the path safely.
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.retry_policy = retry_policy or LlmRetryPolicy()

    # ---- public API ---------------------------------------------------

    def chat(
        self,
        messages: list[LlmMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        trajectory: Any = None,
    ) -> LlmResponse:
        """Call ``POST {base_url}/chat/completions`` and return the response.

        Retries transient failures (429/5xx/network) per :attr:`retry_policy`.

        When *tools* is given, it is forwarded as the OpenAI ``tools`` payload
        and any ``tool_calls`` the model returns are parsed into
        :attr:`LlmResponse.tool_calls` (each a :class:`LlmToolCall`).

        *trajectory* (ADR-0017, opt-in) is an optional :class:`TrajectoryLogger`;
        when provided, a ``request/header`` and ``request/context`` event are
        recorded before the request is sent.

        Raises :class:`LlmApiError` on HTTP failure or malformed payload.
        """
        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        if trajectory is not None:
            _record_llm_trajectory(trajectory, body, max_tokens)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        last_exc: _RetryableError | None = None
        for attempt in range(self.retry_policy.max_retries + 1):
            if attempt > 0:
                time.sleep(self.retry_policy.delay_for(attempt - 1))
            try:
                return self._post_once(url, payload, timeout=timeout)
            except _RetryableError as exc:
                last_exc = exc
                if attempt >= self.retry_policy.max_retries:
                    raise exc.api_error from exc
        assert last_exc is not None
        raise last_exc.api_error

    def stream(
        self,
        messages: list[LlmMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> Iterator[LlmStreamChunk]:
        """Stream a chat completion, yielding one :class:`LlmStreamChunk` per delta.

        The request uses ``stream: true``; the response is parsed as
        server-sent events (``data: {json}`` lines). Chunks with empty content
        deltas (e.g. role-only or a trailing ``[DONE]``) are skipped.

        Retries transient failures per :attr:`retry_policy` (only before any
        chunk has been yielded — once streaming begins, a mid-stream error is
        raised to the caller instead of re-streaming and duplicating chunks).
        """
        url = f"{self.base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "stream": True,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

        last_exc: _RetryableError | None = None
        streamed = False
        for attempt in range(self.retry_policy.max_retries + 1):
            if attempt > 0:
                time.sleep(self.retry_policy.delay_for(attempt - 1))
            try:
                for chunk in self._stream_once(url, payload, timeout=timeout):
                    streamed = True
                    yield chunk
                return
            except _RetryableError as exc:
                last_exc = exc
                # P1-6 修复：一旦已有任何 token 产出（流式已开始），断流后
                # 重试会从第 0 个 token 重新流，导致调用方收到重复前缀。
                # 此时不再重试，把错误抛给调用方（其已持有部分 chunk）。
                if streamed:
                    raise exc.api_error from exc
                if attempt >= self.retry_policy.max_retries:
                    raise exc.api_error from exc
        assert last_exc is not None
        raise last_exc.api_error

    def count_tokens(self, text: str) -> int:
        """Approximate the number of tokens in *text*.

        Uses the ``tiktoken`` library when installed (accurate for common
        OpenAI models); otherwise falls back to a deterministic heuristic of
        ``ceil(len(text) / 4)``, which is a reasonable approximation for
        mixed English/CJK text. Returns 0 for empty input.
        """
        return count_tokens(text)

    # ---- internals -----------------------------------------------------

    def _post_once(
        self, url: str, payload: bytes, timeout: float | None
    ) -> LlmResponse:
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with urllib.request.urlopen(
                req, timeout=timeout if timeout is not None else self.timeout
            ) as resp:
                raw_bytes = resp.read()
        except urllib.error.HTTPError as e:
            text = ""
            try:
                text = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
            exc = LlmApiError(
                f"LLM HTTP {e.code}: {text or e.reason}", status_code=e.code
            )
            if _is_transient(e.code):
                raise _RetryableError.from_api_error(exc) from e
            raise exc from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # socket.timeout surfaces as a bare TimeoutError, not a URLError,
            # so it must be caught explicitly or the retry policy silently
            # skips the most common transient failure (slow LLM responses).
            reason = getattr(e, "reason", None) or str(e)
            exc = LlmApiError(f"LLM network error: {reason}")
            raise _RetryableError.from_api_error(exc) from e

        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise LlmApiError(f"LLM returned non-JSON body: {e}") from e

        return self._parse_response(data)

    def _stream_once(
        self, url: str, payload: bytes, timeout: float | None
    ) -> Iterator[LlmStreamChunk]:
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        req.add_header("Accept", "text/event-stream")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            resp = urllib.request.urlopen(
                req, timeout=timeout if timeout is not None else self.timeout
            )
        except urllib.error.HTTPError as e:
            text = ""
            try:
                text = e.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
            exc = LlmApiError(
                f"LLM HTTP {e.code}: {text or e.reason}", status_code=e.code
            )
            if _is_transient(e.code):
                raise _RetryableError.from_api_error(exc) from e
            raise exc from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # socket.timeout surfaces as a bare TimeoutError, not a URLError,
            # so it must be caught explicitly or the retry policy silently
            # skips the most common transient failure (slow LLM responses).
            reason = getattr(e, "reason", None) or str(e)
            exc = LlmApiError(f"LLM network error: {reason}")
            raise _RetryableError.from_api_error(exc) from e

        try:
            with resp:
                try:
                    for chunk in _parse_sse_stream(resp):
                        yield chunk
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    # 流式进行中也可能断流（如连接重置）——同样按可重试错误
                    # 抛出，由 stream() 决定是否重试（已产出 chunk 则不重试）。
                    reason = getattr(e, "reason", None) or str(e)
                    exc = LlmApiError(f"LLM network error during stream: {reason}")
                    raise _RetryableError.from_api_error(exc) from e
        finally:
            resp.close()

    def _parse_response(self, data: dict[str, Any]) -> LlmResponse:
        """Extract the assistant message from an OpenAI-style response."""
        try:
            choices = data.get("choices") or []
            if not choices:
                raise LlmApiError(f"LLM response has no choices: {data}")
            first = choices[0]
            msg = first.get("message") or {}
            content = msg.get("content") or ""
            finish = first.get("finish_reason", "")
            raw_calls = msg.get("tool_calls") or []
            tool_calls = [
                LlmToolCall.from_dict(tc)
                for tc in raw_calls
                if isinstance(tc, dict)
            ]
        except (KeyError, TypeError, IndexError) as e:
            raise LlmApiError(f"malformed LLM response: {e}: {data}") from e
        return LlmResponse(
            content=content,
            model=data.get("model", ""),
            finish_reason=finish,
            tool_calls=tool_calls,
            raw=data,
        )

    def chat_json(
        self,
        messages: list[LlmMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Like :meth:`chat` but parses the assistant content as JSON.

        Injects a ``"respond with valid JSON only"`` instruction and falls
        back to extracting the first ``{...}`` or ``[...]`` block when the
        model wraps JSON in prose / markdown fences.
        """
        instr = LlmMessage(
            role="system",
            content="You MUST respond with valid JSON only. No prose, no markdown fences.",
        )
        response = self.chat(
            [instr, *messages],
            model=model,
            temperature=temperature,
            timeout=timeout,
        )
        return _extract_json(response.content)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_llm_client(
    provider: str | None = None,
    model: str | None = None,
    settings: Settings | None = None,
    retry_policy: LlmRetryPolicy | None = None,
) -> LlmClient:
    """Build an :class:`LlmClient` from Settings.

    When *provider* or *model* are None, fall back to
    ``Settings.hermes_llm_provider`` / ``Settings.hermes_llm_model``.

    *retry_policy* defaults to a conservative ``max_retries=2`` exponential
    backoff so transient 429/5xx failures are retried automatically. Pass
    ``LlmRetryPolicy(max_retries=0)`` to disable.

    Raises :class:`LlmConfigError` when the provider is unconfigured.
    """
    s = settings or get_settings()
    provider = (provider or s.hermes_llm_provider).strip()
    model = model or s.hermes_llm_model
    base_url, api_key = resolve_provider(provider, settings=s)
    if retry_policy is None:
        retry_policy = LlmRetryPolicy(max_retries=2)
    return LlmClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=s.hermes_llm_timeout,
        temperature=s.hermes_llm_temperature,
        retry_policy=retry_policy,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_llm_trajectory(
    trajectory: Any, body: dict[str, Any], max_tokens: int | None
) -> None:
    """Record request header/context events to a trajectory logger (best-effort).

    ADR-0017: the direct-LLM path records what was sent so it can be replayed.
    A failure to record is non-fatal here (the LLM call proceeds) — the
    orchestrator dispatch path, by contrast, treats recording as fail-loud.
    """
    try:
        seq = trajectory.record(
            "request/header",
            {
                "model": body["model"],
                "temperature": body["temperature"],
                "max_tokens": max_tokens,
            },
        )
        trajectory.record(
            "request/context",
            {"request_seq": seq, "messages": body["messages"]},
        )
    except Exception as exc:  # noqa: BLE001 — recording is best-effort
        logger.warning("failed to record LLM trajectory: %s", exc)


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort parse of JSON from an LLM response.

    Handles three cases in order:
      1. Whole text is valid JSON.
      2. ```json ... ``` fenced block.
      3. First ``{...}`` substring.
    """
    text = text.strip()
    # Case 1: direct parse
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {"value": v}
    except json.JSONDecodeError:
        pass
    # Case 2: strip markdown fences
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        inner = "\n".join(lines).strip()
        try:
            v = json.loads(inner)
            return v if isinstance(v, dict) else {"value": v}
        except json.JSONDecodeError:
            pass
    # Case 3: first balanced {...} block (scan brackets so multiple objects or
    # trailing braces don't cause over-extraction).
    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    fragment = text[start : i + 1]
                    try:
                        v = json.loads(fragment)
                        return v if isinstance(v, dict) else {"value": v}
                    except json.JSONDecodeError:
                        break
    # Case 4 (P2-9)：文档声称支持 `[...]` 数组但未实现。解析首个平衡的数组
    # 字面量，与对象一致地归一为 {"value": [...]}。
    start = text.find("[")
    if start != -1:
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    fragment = text[start : i + 1]
                    try:
                        v = json.loads(fragment)
                        return {"value": v}
                    except json.JSONDecodeError:
                        break
    raise LlmApiError(f"could not extract JSON from LLM response: {text[:200]!r}")


# ---------------------------------------------------------------------------
# Retry / streaming / token-counting helpers
# ---------------------------------------------------------------------------


class _RetryableError(Exception):
    """Internal marker for transient LLM errors that should be retried.

    Wraps the original :class:`LlmApiError`; ``chat``/``stream`` catch this,
    sleep, and re-attempt. When retries are exhausted the wrapped error is
    re-raised as-is so callers see a normal :class:`LlmApiError`.
    """

    def __init__(self, api_error: LlmApiError) -> None:
        super().__init__(str(api_error))
        self.api_error = api_error

    @classmethod
    def from_api_error(cls, api_error: LlmApiError) -> _RetryableError:
        return cls(api_error)


def _is_transient(status_code: int) -> bool:
    """Return True for status codes worth retrying (429 / 5xx)."""
    return status_code == 429 or 500 <= status_code < 600


def _parse_sse_stream(resp: Any) -> Iterator[LlmStreamChunk]:
    """Parse a streaming SSE response body into :class:`LlmStreamChunk` items.

    Handles the OpenAI chat-completions stream format: ``data: {json}`` lines
    separated by blank lines, ending with ``data: [DONE]``. Delta content is
    read from ``choices[0].delta.content``.
    """
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            data = line[len("data:"):].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            first = choices[0]
            delta = first.get("delta") or {}
            content = delta.get("content")
            finish = first.get("finish_reason") or ""
            if not content:
                # Skip role-only / empty deltas unless it carries a finish reason.
                if finish:
                    yield LlmStreamChunk(
                        content="", finish_reason=finish, model=obj.get("model", ""), raw=obj
                    )
                continue
            yield LlmStreamChunk(
                content=content,
                finish_reason=finish,
                model=obj.get("model", ""),
                raw=obj,
            )


def _token_count_fallback(text: str) -> int:
    """Deterministic token-count heuristic (≈4 chars/token)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """Approximate the number of tokens in *text*.

    Uses the ``tiktoken`` library when installed (accurate for OpenAI models);
    otherwise falls back to a ``len(text)/4`` heuristic. ``model`` is only used
    when tiktoken is available and is ignored by the fallback.

    This function is deterministic and never raises: any error loading
    tiktoken or encoding the text degrades to the fallback heuristic.
    """
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore[import-not-found]

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:  # noqa: BLE001 — tiktoken optional; degrade gracefully
        return _token_count_fallback(text)
