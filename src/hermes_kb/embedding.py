"""Embedding 服务：Provider 抽象。

支持的 Provider：
- hash：SHA256 确定性向量（默认，无外部依赖，仅供开发测试）
- openai：OpenAI 兼容 /embeddings 接口（含智谱、Moonshot 等）
- sentence_transformers：本地模型（如 bge-small-zh，可选依赖）

设计要点：
- 同一后端内向量维度一致；切换 provider 后需重建索引（M2 提供 reindex API）
- 任何后端异常都降级 Hash，保证服务可用
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, Protocol

from hermes_kb.config import get_settings


class EmbeddingBackend(Protocol):
    """Embedding 后端协议。"""

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Iterable[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# Hash Mock 后端
# ---------------------------------------------------------------------------
class HashEmbeddingBackend:
    """SHA256 确定性向量（无外部依赖）。"""

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or get_settings().embedding_dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self._dim
        vec = [0.0] * self._dim
        for tok in self._tokenize(text):
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            for i in range(self._dim):
                b = h[i % len(h)]
                sign = 1.0 if (b & 1) else -1.0
                vec[i] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """字符 bigram + trigram，中文友好（去掉单字降低噪声）。"""
        segments = re.split(r"[\s,，。！？、；：""''（）()【】\[\]{}]+", text)
        segments = [s for s in segments if s]
        if not segments:
            return []
        tokens: list[str] = []
        for seg in segments:
            if len(seg) <= 2:
                tokens.append(seg)
                continue
            if re.fullmatch(r"[A-Za-z0-9\-_]+", seg):
                tokens.append(seg)
                continue
            for i in range(len(seg) - 1):
                tokens.append(seg[i : i + 2])
            for i in range(len(seg) - 2):
                tokens.append(seg[i : i + 3])
        return tokens


# ---------------------------------------------------------------------------
# OpenAI 兼容后端
# ---------------------------------------------------------------------------
class OpenAIEmbeddingBackend:
    """OpenAI 兼容 /embeddings 接口。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._dim: int | None = None  # 首次调用时确定

    @property
    def dim(self) -> int:
        if self._dim is None:
            # 用一次探针确定维度（OpenAI text-embedding-3-small=1536，智谱 embedding-3=2048）
            try:
                v = self._call_api(["probe"])[0]
                self._dim = len(v)
            except Exception:
                # 探针失败回退配置值
                self._dim = self.settings.embedding_dim
        return self._dim

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        texts_list = list(texts)
        if not texts_list:
            return []
        try:
            return self._call_api(texts_list)
        except Exception:
            # 降级 Hash
            backend = HashEmbeddingBackend(self.settings.embedding_dim)
            return backend.embed(texts_list)

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        import httpx

        url = f"{self.settings.embedding_base_url.rstrip('/')}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.settings.embedding_model,
            "input": texts,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        embeddings = [item["embedding"] for item in data["data"]]
        if embeddings:
            self._dim = len(embeddings[0])
        return embeddings


# ---------------------------------------------------------------------------
# sentence-transformers 本地后端（bge-small-zh 等）
# ---------------------------------------------------------------------------
class SentenceTransformerBackend:
    """本地 sentence-transformers 模型后端。

    依赖可选：sentence-transformers + torch。缺失时降级 Hash。
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None
        self._dim: int | None = None
        self._load_error: str | None = None

    def _ensure_model(self):
        if self._model is not None or self._load_error:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.settings.embedding_st_model)
        except Exception as e:
            self._load_error = str(e)

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._ensure_model()
            if self._model is not None:
                try:
                    self._dim = self._model.get_sentence_embedding_dimension()
                except Exception:
                    self._dim = self.settings.embedding_dim
            else:
                self._dim = self.settings.embedding_dim
        return self._dim

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        texts_list = list(texts)
        if not texts_list:
            return []
        self._ensure_model()
        if self._model is None:
            # 降级 Hash
            return HashEmbeddingBackend(self.settings.embedding_dim).embed(texts_list)
        try:
            vecs = self._model.encode(texts_list, normalize_embeddings=True)
            return [list(map(float, v)) for v in vecs]
        except Exception:
            return HashEmbeddingBackend(self.settings.embedding_dim).embed(texts_list)


# ---------------------------------------------------------------------------
# 服务入口
# ---------------------------------------------------------------------------
class EmbeddingService:
    """Embedding 服务：根据配置选择后端。"""

    def __init__(self, dim: int | None = None) -> None:
        self.settings = get_settings()
        self._backend: EmbeddingBackend = self._select_backend()
        # dim 参数仅 hash 后端使用（保持向后兼容）
        if dim is not None and isinstance(self._backend, HashEmbeddingBackend):
            self._backend = HashEmbeddingBackend(dim)

    def _select_backend(self) -> EmbeddingBackend:
        provider = self.settings.embedding_provider.lower()
        if provider == "openai" and self.settings.embedding_available:
            return OpenAIEmbeddingBackend()
        if provider == "sentence_transformers":
            return SentenceTransformerBackend()
        return HashEmbeddingBackend()

    @property
    def dim(self) -> int:
        return self._backend.dim

    @property
    def backend_name(self) -> str:
        return self._backend.__class__.__name__

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        return self._backend.embed(texts)

    def embed_one(self, text: str) -> list[float]:
        result = self.embed([text])
        return result[0] if result else [0.0] * self.dim
