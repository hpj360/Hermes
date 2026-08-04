"""SecretSource：可插拔的密钥来源抽象。

借鉴 Hermes Agent v0.19.0 的 SecretSource 能力，适配为控制平面层的密钥管理。
默认从 .env 文件读取（向后兼容），预留 Bitwarden/1Password 接口。

设计约束：
- 零外部运行时依赖（Bitwarden/1Password 实现是未来 extra，不进核心依赖）
- 保持向后兼容：不配置时走默认 EnvFileSecretSource
- SecretSource 通过 HERMES_SECRET_SOURCE 环境变量选择
"""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


class SecretSource(ABC):
    """密钥来源抽象接口。"""

    @abstractmethod
    def get_secret(self, key: str, default: str | None = None) -> str | None:
        """获取密钥值。返回 None 表示未找到。"""

    @abstractmethod
    def is_available(self) -> bool:
        """检查此 SecretSource 是否可用（如 bitwarden CLI 是否安装）。"""

    @abstractmethod
    def source_name(self) -> str:
        """返回来源名称（用于诊断/日志）。"""


class EnvFileSecretSource(SecretSource):
    """从 .env 文件读取密钥（默认实现，向后兼容）。

    查询顺序：先查进程环境变量（已加载的），再查 .env 文件内容。
    不修改进程环境变量，仅读取 .env 文件解析出的键值映射。
    """

    def __init__(self, env_file: Path | None = None) -> None:
        # 未指定 env_file 时使用项目根目录的 .env（与 config.py 保持一致）
        if env_file is None:
            env_file = Path(__file__).resolve().parents[2] / ".env"
        self._env_file = env_file
        # 解析 .env 文件为键值映射；文件不存在时为空映射
        self._values: dict[str, str | None] = {}
        if env_file.exists():
            self._values = dict(dotenv_values(env_file))

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        # 先查进程环境变量（已加载的，包括 bootstrap_env 注入的）
        env_val = os.environ.get(key)
        if env_val is not None:
            return env_val
        # 再查 .env 文件解析出的值
        file_val = self._values.get(key)
        if file_val is not None:
            return file_val
        return default

    def is_available(self) -> bool:
        # 始终可用：最坏情况只是文件不存在
        return True

    def source_name(self) -> str:
        return "env_file"


class EnvVarSecretSource(SecretSource):
    """从进程环境变量读取密钥。"""

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)

    def is_available(self) -> bool:
        return True

    def source_name(self) -> str:
        return "env_var"


class BitwardenSecretSource(SecretSource):
    """Bitwarden CLI 密钥来源（预留接口，未实现具体逻辑）。

    未来实现需要：
    1. 检查 bw CLI 是否安装
    2. 检查 BW_SESSION 环境变量
    3. 通过 `bw get password <item>` 获取密钥

    当前为占位实现，is_available() 返回 False，get_secret() 抛 NotImplementedError。
    """

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        raise NotImplementedError(
            "BitwardenSecretSource 尚未实现。"
            "请使用 HERMES_SECRET_SOURCE=env_file（默认）或贡献实现。"
        )

    def is_available(self) -> bool:
        # 占位实现：始终不可用
        return False

    def source_name(self) -> str:
        return "bitwarden"


class OnePasswordSecretSource(SecretSource):
    """1Password CLI 密钥来源（预留接口，未实现具体逻辑）。

    未来实现需要：
    1. 检查 op CLI 是否安装
    2. 检查 OP_SESSION 环境变量
    3. 通过 `op item get <item> --field password` 获取密钥

    当前为占位实现，is_available() 返回 False，get_secret() 抛 NotImplementedError。
    """

    def get_secret(self, key: str, default: str | None = None) -> str | None:
        raise NotImplementedError(
            "OnePasswordSecretSource 尚未实现。"
            "请使用 HERMES_SECRET_SOURCE=env_file（默认）或贡献实现。"
        )

    def is_available(self) -> bool:
        # 占位实现：始终不可用
        return False

    def source_name(self) -> str:
        return "onepassword"


# 已注册的 SecretSource 名称 → 类映射
SECRET_SOURCES: dict[str, type[SecretSource]] = {
    "env_file": EnvFileSecretSource,
    "env_var": EnvVarSecretSource,
    "bitwarden": BitwardenSecretSource,
    "onepassword": OnePasswordSecretSource,
}

# 默认 SecretSource 名称
DEFAULT_SECRET_SOURCE = "env_file"


def get_secret_source() -> SecretSource:
    """根据 HERMES_SECRET_SOURCE 环境变量返回 SecretSource 实例。

    - 默认：env_file
    - 未知名称或选择的 source 不可用时，graceful degradation：fallback 到 env_file
      并向 stderr 打印 warning。
    """
    requested = os.environ.get("HERMES_SECRET_SOURCE", DEFAULT_SECRET_SOURCE).strip().lower()
    cls = SECRET_SOURCES.get(requested)
    if cls is None:
        print(
            f"warning: 未知 SecretSource '{requested}'，回退到 {DEFAULT_SECRET_SOURCE}",
            file=sys.stderr,
        )
        return EnvFileSecretSource()

    source = cls()
    if not source.is_available():
        print(
            f"warning: SecretSource '{requested}' 不可用，回退到 {DEFAULT_SECRET_SOURCE}",
            file=sys.stderr,
        )
        return EnvFileSecretSource()
    return source


def list_available_sources() -> list[dict[str, Any]]:
    """列出所有 SecretSource 及其可用性状态。

    用于 `hermes secrets list` 命令。每项包含：
    - name: 注册名（HERMES_SECRET_SOURCE 取值）
    - source_name: source_name() 返回值（诊断用）
    - available: is_available() 返回值
    """
    result: list[dict[str, Any]] = []
    for name, cls in SECRET_SOURCES.items():
        # 占位实现的 is_available() 不抛异常，可安全实例化
        source = cls()
        result.append(
            {
                "name": name,
                "source_name": source.source_name(),
                "available": source.is_available(),
            }
        )
    return result
