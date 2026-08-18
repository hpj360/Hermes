"""Environment configuration loader for Hermes.

Hermes inherits common account/API environment variables from the main project
repositories. The loading precedence (highest to lowest) is:

1. Process environment variables already set
2. Hermes own `.env` file
3. Main project `.env` files (root and OpenClaw)
4. Default values defined in `Settings`

All user-writable state (config, cache, logs) stays inside the project root
to stay within sandbox allow-listed directories.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    """Resolve the project/data root for default paths.

    P2-1：``Path(__file__).resolve().parents[2]`` 在 pip 安装后指向
    ``site-packages`` 的上两级（即 Python 安装目录旁），写入 ``.state`` /
    ``.cache`` 会污染系统目录。优先读 ``HERMES_DATA_DIR`` 环境变量；未设置时
    回退到源码树（``parents[2]``）保持开发态兼容。
    """
    env = os.environ.get("HERMES_DATA_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings inherited from the main project environments."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def __repr__(self) -> str:
        """脱敏 repr：不打印任何 API key / token / 凭据值（P2-11）。

        用字段名后缀启发式识别敏感字段并掩码为 ``<redacted>``，避免
        ``print(settings)`` 或日志把明文密钥写进终端/日志。
        """
        sensitive = ("key", "token", "secret", "password", "credential", "apikey")
        parts: list[str] = []
        for name, value in self.__dict__.items():
            n = name.lower()
            shown = "<redacted>" if any(s in n for s in sensitive) else repr(value)
            parts.append(f"{name}={shown}")
        return f"Settings({', '.join(parts)})"

    # -------------------------------------------------------------------------
    # OpenClaw gateway
    # -------------------------------------------------------------------------
    openclaw_llm_api_key: str | None = Field(default=None, alias="OPENCLAW_LLM_API_KEY")
    openclaw_gateway_port: int = Field(default=18789, alias="OPENCLAW_GATEWAY_PORT")
    openclaw_gateway_token: str | None = Field(default=None, alias="OPENCLAW_GATEWAY_TOKEN")
    openclaw_gateway_password: str | None = Field(default=None, alias="OPENCLAW_GATEWAY_PASSWORD")
    openclaw_state_dir: Path | None = Field(default=None, alias="OPENCLAW_STATE_DIR")
    openclaw_config_path: Path | None = Field(default=None, alias="OPENCLAW_CONFIG_PATH")

    # -------------------------------------------------------------------------
    # Workbench API token (U2 auth hardening)
    # -------------------------------------------------------------------------
    # Single Bearer token protecting /wb/* and /api/* endpoints. When unset,
    # the workbench server refuses to bind non-loopback addresses (unless
    # --insecure is passed) instead of silently running open (dev-mode leak).
    hermes_api_token: str | None = Field(default=None, alias="HERMES_API_TOKEN")

    # -------------------------------------------------------------------------
    # Major model providers (OpenAI-compatible or native)
    # -------------------------------------------------------------------------
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str | None = Field(default=None, alias="ANTHROPIC_BASE_URL")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )

    # -------------------------------------------------------------------------
    # Regional / alternative providers
    # -------------------------------------------------------------------------
    # Moonshot AI (Kimi)
    moonshot_api_key: str | None = Field(default=None, alias="MOONSHOT_API_KEY")
    moonshot_base_url: str = Field(
        default="https://api.moonshot.cn/v1", alias="MOONSHOT_BASE_URL"
    )
    # Zhipu AI (GLM / z.ai)
    zai_api_key: str | None = Field(default=None, alias="ZAI_API_KEY")
    zai_base_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", alias="ZAI_BASE_URL")
    # Baidu Qianfan
    qianfan_access_key: str | None = Field(default=None, alias="QIANFAN_ACCESS_KEY")
    qianfan_secret_key: str | None = Field(default=None, alias="QIANFAN_SECRET_KEY")
    # Alibaba Qwen / DashScope
    dashscope_api_key: str | None = Field(default=None, alias="DASHSCOPE_API_KEY")
    # Xiaomi MiMo
    xiaomi_api_key: str | None = Field(default=None, alias="XIAOMI_API_KEY")
    # MiniMax
    minimax_api_key: str | None = Field(default=None, alias="MINIMAX_API_KEY")
    minimax_group_id: str | None = Field(default=None, alias="MINIMAX_GROUP_ID")
    # Mistral AI
    mistral_api_key: str | None = Field(default=None, alias="MISTRAL_API_KEY")
    # Novita AI
    novita_api_key: str | None = Field(default=None, alias="NOVITA_API_KEY")
    novita_base_url: str = Field(
        default="https://api.novita.ai/v3/openai", alias="NOVITA_BASE_URL"
    )
    # Ollama (local)
    ollama_base_url: str = Field(default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL")
    # ModelScope (OpenAI-compatible gateway)
    modelscope_api_key: str | None = Field(default=None, alias="MODELSCOPE_API_KEY")
    modelscope_base_url: str = Field(
        default="https://api-inference.modelscope.cn/v1", alias="MODELSCOPE_BASE_URL"
    )
    # OpenAI Live / gateway proxies
    openclaw_live_openai_key: str | None = Field(
        default=None, alias="OPENCLAW_LIVE_OPENAI_KEY"
    )
    openclaw_live_anthropic_key: str | None = Field(
        default=None, alias="OPENCLAW_LIVE_ANTHROPIC_KEY"
    )
    openclaw_live_gemini_key: str | None = Field(
        default=None, alias="OPENCLAW_LIVE_GEMINI_KEY"
    )
    ai_gateway_api_key: str | None = Field(default=None, alias="AI_GATEWAY_API_KEY")
    synthetic_api_key: str | None = Field(default=None, alias="SYNTHETIC_API_KEY")

    openclaw_model_primary: str = Field(
        default="anthropic/claude-sonnet-4-5", alias="OPENCLAW_MODEL_PRIMARY"
    )
    openclaw_model_fallback: str = Field(
        default="openai/gpt-4o", alias="OPENCLAW_MODEL_FALLBACK"
    )

    # -------------------------------------------------------------------------
    # Channels
    # -------------------------------------------------------------------------
    slack_bot_token: str | None = Field(default=None, alias="SLACK_BOT_TOKEN")
    slack_app_token: str | None = Field(default=None, alias="SLACK_APP_TOKEN")
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    discord_bot_token: str | None = Field(default=None, alias="DISCORD_BOT_TOKEN")
    mattermost_bot_token: str | None = Field(default=None, alias="MATTERMOST_BOT_TOKEN")
    mattermost_url: str | None = Field(default=None, alias="MATTERMOST_URL")
    zalo_bot_token: str | None = Field(default=None, alias="ZALO_BOT_TOKEN")
    openclaw_twitch_access_token: str | None = Field(
        default=None, alias="OPENCLAW_TWITCH_ACCESS_TOKEN"
    )
    feishu_app_id: str | None = Field(default=None, alias="FEISHU_APP_ID")
    feishu_app_secret: str | None = Field(default=None, alias="FEISHU_APP_SECRET")
    feishu_verification_token: str | None = Field(
        default=None, alias="FEISHU_VERIFICATION_TOKEN"
    )

    # -------------------------------------------------------------------------
    # Tools / search / media
    # -------------------------------------------------------------------------
    brave_api_key: str | None = Field(default=None, alias="BRAVE_API_KEY")
    perplexity_api_key: str | None = Field(default=None, alias="PERPLEXITY_API_KEY")
    firecrawl_api_key: str | None = Field(default=None, alias="FIRECRAWL_API_KEY")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    elevenlabs_api_key: str | None = Field(default=None, alias="ELEVENLABS_API_KEY")
    xi_api_key: str | None = Field(default=None, alias="XI_API_KEY")
    deepgram_api_key: str | None = Field(default=None, alias="DEEPGRAM_API_KEY")

    # -------------------------------------------------------------------------
    # Integrations
    # -------------------------------------------------------------------------
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    notion_api_key: str | None = Field(default=None, alias="NOTION_API_KEY")
    trello_api_key: str | None = Field(default=None, alias="TRELLO_API_KEY")
    trello_api_token: str | None = Field(default=None, alias="TRELLO_API_TOKEN")
    tailscale_auth_key: str | None = Field(default=None, alias="TAILSCALE_AUTH_KEY")

    # IMA 知识库 (Tencent IMA OpenAPI)
    ima_openapi_clientid: str | None = Field(default=None, alias="IMA_OPENAPI_CLIENTID")
    ima_openapi_apikey: str | None = Field(default=None, alias="IMA_OPENAPI_APIKEY")
    ima_openapi_base_url: str = Field(
        default="https://ima.qq.com", alias="IMA_OPENAPI_BASE_URL"
    )

    # -------------------------------------------------------------------------
    # Skillhub
    # -------------------------------------------------------------------------
    skillhub_api_base: str = Field(default="https://lightmake.site", alias="SKILLHUB_API_BASE")
    # Skill marketplace registry catalog URL (P3-4). Empty = no remote registry.
    hermes_skill_registry: str = Field(default="", alias="HERMES_SKILL_REGISTRY")
    skillhub_cos_bucket: str = Field(
        default="skills-store-1259584892", alias="SKILLHUB_COS_BUCKET"
    )
    skillhub_cos_region: str = Field(default="ap-guangzhou", alias="SKILLHUB_COS_REGION")

    # -------------------------------------------------------------------------
    # Hermes specific
    # -------------------------------------------------------------------------
    hermes_log_level: str = Field(default="INFO", alias="HERMES_LOG_LEVEL")
    hermes_main_repo_path: Path = Field(
        default=Path("/workspace/OpenClaw/openclaw-main"),
        alias="HERMES_MAIN_REPO_PATH",
    )
    hermes_project_root: Path = Field(
        default=_project_root(),
        alias="HERMES_PROJECT_ROOT",
    )
    hermes_state_dir: Path = Field(
        default=_project_root() / ".state",
        alias="HERMES_STATE_DIR",
    )
    hermes_cache_dir: Path = Field(
        default=_project_root() / ".cache",
        alias="HERMES_CACHE_DIR",
    )
    hermes_profile_path: Path = Field(
        default=_project_root() / "data" / "profile.json",
        alias="HERMES_PROFILE_PATH",
    )
    # MemOS local plugin integration
    memos_enabled: bool = Field(default=False, alias="MEMOS_ENABLED")
    memos_base_url: str = Field(default="http://127.0.0.1:18800", alias="MEMOS_BASE_URL")
    # M4: pluggable memory backend. local_rrf (default) | mem0 | memos.
    hermes_memory_backend: str = Field(default="local_rrf", alias="HERMES_MEMORY_BACKEND")
    hermes_memory_sync_enabled: bool = Field(default=False, alias="HERMES_MEMORY_SYNC_ENABLED")
    hermes_memory_sync_batch_size: int = Field(
        default=10, alias="HERMES_MEMORY_SYNC_BATCH_SIZE"
    )
    # Mem0 backend overrides. Empty = reuse hermes_llm_model / ollama_embed_model.
    hermes_mem0_llm_model: str = Field(default="", alias="HERMES_MEM0_LLM_MODEL")
    hermes_mem0_embed_model: str = Field(default="", alias="HERMES_MEM0_EMBED_MODEL")
    # hermes-kb service integration (P2-1). Empty = not configured → /kb/search
    # degrades gracefully instead of proxying.
    hermes_kb_base_url: str = Field(default="", alias="HERMES_KB_BASE_URL")
    # Ollama embedding settings
    ollama_embed_url: str = Field(default="http://localhost:11434", alias="OLLAMA_EMBED_URL")
    ollama_embed_model: str = Field(default="nomic-embed-text", alias="OLLAMA_EMBED_MODEL")
    # LLM integration: which provider/model the workbench agent should use.
    # provider is one of: zai/glm, ollama, openai, openrouter, moonshot, etc.
    # (any name returned by Settings.configured_providers()).
    hermes_llm_provider: str = Field(default="ollama", alias="HERMES_LLM_PROVIDER")
    # P2-13：默认 provider=ollama（本地）时，默认 model 必须匹配本地 ollama
    # 通用模型，避免 gpt-3.5-turbo 在本地 ollama 下必然 model-not-found。
    hermes_llm_model: str = Field(default="llama3.2", alias="HERMES_LLM_MODEL")
    hermes_llm_timeout: float = Field(default=60.0, alias="HERMES_LLM_TIMEOUT")
    hermes_llm_temperature: float = Field(default=0.2, alias="HERMES_LLM_TEMPERATURE")

    # ADR-0018: 用户自定义 Agent Preset 目录。None = 使用 hermes_state_dir/presets。
    hermes_presets_dir: str | None = Field(default=None, alias="HERMES_PRESETS_DIR")
    # A1 (Reasonix borrow): 上下文摘要缓存目录。None = hermes_cache_dir。
    hermes_context_summary_dir: str | None = Field(
        default=None, alias="HERMES_CONTEXT_SUMMARY_DIR"
    )

    # Search paths that are consulted for inherited .env files.
    inherit_env_paths: ClassVar[list[Path]] = [
        Path("/workspace/.env"),
        Path("/workspace/OpenClaw/openclaw-main/.env"),
    ]

    def configured_providers(self) -> list[str]:
        """Return names of LLM providers that have API keys configured."""
        provider_keys = [
            ("openai", self.openai_api_key),
            ("anthropic", self.anthropic_api_key),
            ("gemini", self.gemini_api_key or self.google_api_key),
            ("openrouter", self.openrouter_api_key),
            ("moonshot", self.moonshot_api_key),
            ("zai/glm", self.zai_api_key),
            ("qianfan", self.qianfan_access_key and self.qianfan_secret_key),
            ("dashscope/qwen", self.dashscope_api_key),
            ("xiaomi", self.xiaomi_api_key),
            ("minimax", self.minimax_api_key),
            ("mistral", self.mistral_api_key),
            ("novita", self.novita_api_key),
            ("ollama", True),  # local, no key needed by default
            ("modelscope", self.modelscope_api_key),
        ]
        return [name for name, key in provider_keys if key]

    def missing_required(self) -> list[str]:
        """Return a list of environment variables that should be checked.

        Hermes itself does not strictly require any key to be present;
        this returns an empty list by default and is intended as a hook
        for subcommands to surface missing credentials when needed.
        """
        return []


def load_inherited_env() -> None:
    """Load environment variables from inherited .env files (pointer-style).

    Inherited paths come from two sources, in order:

    1. Hard-coded defaults in :attr:`Settings.inherit_env_paths` (back-compat
       with the original Linux sandbox layout).
    2. ``HERMES_INHERIT_ENV_PATHS`` — a path-separator-delimited list of extra
       ``.env`` files. This is *pointer-style* inheritance: the paths are
       referenced, not copied, so a single source of truth can be shared
       across environments without duplication.

    Existing non-empty environment variables are never overwritten.
    """
    for path in Settings.inherit_env_paths:
        if path.exists():
            load_dotenv(path, override=False, verbose=False)
    extra = os.environ.get("HERMES_INHERIT_ENV_PATHS", "")
    for raw in extra.split(os.pathsep):
        raw = raw.strip()
        if raw and Path(raw).exists():
            load_dotenv(Path(raw), override=False, verbose=False)


def load_hermes_env() -> None:
    """Load Hermes own .env file if present.

    Existing non-empty environment variables are never overwritten so that
    explicit exports always win.
    """
    env_file = _project_root() / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False, verbose=False)


def bootstrap_env() -> None:
    """Bootstrap environment loading with correct precedence.

    Order (highest wins):
    1. Process environment (already present when the process started).
    2. Hermes local .env.
    3. Inherited main-repo .env files.
    4. Default values in Settings.
    """
    load_hermes_env()
    load_inherited_env()


bootstrap_env()

_hermes_settings: Settings | None = None


def get_settings(force_reload: bool = False) -> Settings:
    """Return cached application settings."""
    global _hermes_settings
    if _hermes_settings is None or force_reload:
        _hermes_settings = Settings()
        # Ensure state/cache dirs exist.
        _hermes_settings.hermes_state_dir.mkdir(parents=True, exist_ok=True)
        _hermes_settings.hermes_cache_dir.mkdir(parents=True, exist_ok=True)
    return _hermes_settings
