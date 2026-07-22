"""配置：所有项可通过环境变量覆盖。"""

from __future__ import annotations

import functools
import os
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_list(key: str, default: list[str]) -> list[str]:
    v = os.environ.get(key)
    if not v:
        return list(default)
    return [x.strip() for x in v.split(",") if x.strip()]


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    raw = v.strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off", ""):
        return False
    # P1-7: 非识别值（如 "disable" / "enable" / "y"）显式报错，
    # 避免用户误以为 "disable" 是关闭（实际静默为 False）。
    raise ValueError(
        f"Invalid boolean value for {key}: {v!r}. "
        f"Expected one of: 1/true/yes/on (True), 0/false/no/off/'' (False)."
    )


@dataclass
class Settings:
    """全局配置。"""

    db_path: str = field(default_factory=lambda: _env_str("KB_DB_PATH", ".hermes_kb/hermes_kb.db"))
    host: str = field(default_factory=lambda: _env_str("KB_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("KB_PORT", 8765))
    cors_origins: list[str] = field(default_factory=lambda: _env_list("KB_CORS", ["*"]))

    # 分片
    chunk_size: int = field(default_factory=lambda: _env_int("KB_CHUNK_SIZE", 500))
    chunk_overlap: int = field(default_factory=lambda: _env_int("KB_CHUNK_OVERLAP", 80))

    # 检索
    top_k: int = field(default_factory=lambda: _env_int("KB_TOP_K", 5))
    rrf_k: int = field(default_factory=lambda: _env_int("KB_RRF_K", 60))
    # 低置信度阈值：RRF score < 此值时返回"未找到"反馈（M1-06）
    min_score_threshold: float = field(default_factory=lambda: float(_env_str("KB_MIN_SCORE", "0.005")))

    # 向量检索扫描上限（A3-1：替代硬编码 LIMIT 10000）
    vector_scan_limit: int = field(default_factory=lambda: _env_int("KB_VECTOR_SCAN_LIMIT", 50000))

    # Embedding Provider（M1-02）
    embedding_dim: int = field(default_factory=lambda: _env_int("KB_EMBEDDING_DIM", 256))
    embedding_provider: str = field(default_factory=lambda: _env_str("KB_EMBEDDING_PROVIDER", "hash"))
    embedding_api_key: str = field(default_factory=lambda: _env_str("KB_EMBEDDING_API_KEY", ""))
    embedding_base_url: str = field(default_factory=lambda: _env_str("KB_EMBEDDING_BASE_URL", "https://api.openai.com/v1"))
    embedding_model: str = field(default_factory=lambda: _env_str("KB_EMBEDDING_MODEL", "text-embedding-3-small"))
    embedding_st_model: str = field(default_factory=lambda: _env_str("KB_EMBEDDING_ST_MODEL", "BAAI/bge-small-zh-v1.5"))

    # LLM Provider（M1-01）
    llm_api_key: str = field(default_factory=lambda: _env_str("KB_LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: _env_str("KB_LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_model: str = field(default_factory=lambda: _env_str("KB_LLM_MODEL", "gpt-4o-mini"))
    llm_provider: str = field(default_factory=lambda: _env_str("KB_LLM_PROVIDER", "openai"))

    # 安全
    query_max_length: int = field(default_factory=lambda: _env_int("KB_QUERY_MAX_LENGTH", 500))

    # 认证（M1-07）
    auth_enabled: bool = field(default_factory=lambda: _env_bool("KB_AUTH_ENABLED", False))
    auth_password: str = field(default_factory=lambda: _env_str("KB_AUTH_PASSWORD", ""))
    auth_username: str = field(default_factory=lambda: _env_str("KB_USERNAME", "admin"))
    jwt_secret: str = field(default_factory=lambda: _env_str("KB_JWT_SECRET", "hermes-kb-default-secret-please-change"))
    jwt_ttl_hours: int = field(default_factory=lambda: _env_int("KB_JWT_TTL_HOURS", 24))

    # 未成年保护（M1-08）
    age_gate_enabled: bool = field(default_factory=lambda: _env_bool("KB_AGE_GATE", True))

    # 调试模式（A1-02）：True 时 500 响应保留 str(exc) 便于排查；False 时隐藏内部信息
    debug: bool = field(default_factory=lambda: _env_bool("KB_DEBUG", False))

    # 查询改写（M2-02）
    query_rewrite_enabled: bool = field(default_factory=lambda: _env_bool("KB_QUERY_REWRITE", True))
    # HyDE（M2-02 可选，默认关闭，W1 末评估后决定）
    hyde_enabled: bool = field(default_factory=lambda: _env_bool("KB_HYDE", False))

    @property
    def llm_available(self) -> bool:
        """是否启用真实 LLM。"""
        if self.llm_provider == "mock":
            return False
        return bool(self.llm_api_key and self.llm_api_key.strip())

    @property
    def embedding_available(self) -> bool:
        """是否启用真实 Embedding。"""
        if self.embedding_provider == "hash":
            return False
        if self.embedding_provider == "sentence_transformers":
            return True
        return bool(self.embedding_api_key and self.embedding_api_key.strip())

    @property
    def db_url(self) -> str:
        p = Path(self.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{p.absolute()}"

    def __post_init__(self) -> None:
        """启动期安全校验（A1-1）。

        - 启用认证时必须显式配置非默认 jwt_secret，否则禁止启动。
        """
        if self.auth_enabled:
            if not self.jwt_secret or not self.jwt_secret.strip():
                raise RuntimeError(
                    "jwt_secret must be set to a non-empty value when "
                    "KB_AUTH_ENABLED=true (set KB_JWT_SECRET env var)"
                )
            if self.jwt_secret == "hermes-kb-default-secret-please-change":
                raise RuntimeError(
                    "jwt_secret is still the default value. Set a unique "
                    "secret via the KB_JWT_SECRET environment variable before "
                    "enabling auth (KB_AUTH_ENABLED=true)."
                )


_SETTINGS: Settings | None = None
_SETTINGS_LOCK = threading.Lock()


@functools.lru_cache(maxsize=1)
def _create_settings() -> Settings:
    """线程安全的单例创建（lru_cache 内部加锁，避免多 worker 竞态）。"""
    return Settings()


def get_settings() -> Settings:
    """获取全局配置单例（线程安全）。

    P1-3: 用 lru_cache 保护单例创建，消除多 worker 下的竞态。
    测试期 override 优先于缓存实例。
    """
    override = _SETTINGS
    if override is not None:
        return override
    return _create_settings()


def reset_settings() -> None:
    """测试用：重置单例（清除 override + 清空 lru_cache）。"""
    global _SETTINGS
    with _SETTINGS_LOCK:
        _SETTINGS = None
    _create_settings.cache_clear()


def override_settings(**kwargs) -> Settings:
    """测试用：覆盖部分配置（线程安全）。"""
    global _SETTINGS
    base = get_settings()
    new = replace(base, **kwargs)
    with _SETTINGS_LOCK:
        _SETTINGS = new
    return new
