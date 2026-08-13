# ADR 0016: 平台凭据加密落盘 + API 脱敏

Status: Accepted
Date: 2026-08-14

## Context

`PlatformAccount` 的 `auth_token` / `refresh_token` 是 `sa.Text` **明文列**（模型
docstring 自认"生产环境应加密存储，此处占位"）。泄露面不止 DB：

- `api/publish.py` 的 `PlatformAccountResponse` 直接回传 `auth_token` / `refresh_token`，
  `GET /accounts` 会把 token 打给前端。
- `app.py` CORS 为 `allow_origins=["*"]`。

生产一部署，token 等于通过 HTTP 明文可拉取。

## Decision

1. **落盘加密**：用 SQLAlchemy `TypeDecorator`（Fernet / AES-GCM）加密 `auth_token` /
   `refresh_token`，密钥来自环境变量（`HERMES_SECRET_KEY`），不落盘、不进 git。
2. **API 脱敏**：`PlatformAccountResponse` 永不回传 token，只回 `has_token: bool`
   （或 masked 形如 `wec***abc`）；写接口与读接口分离。
3. **CORS 收紧**：从 `*` 改为环境变量白名单。
4. **审计脱敏**：`audit.jsonl` / 日志禁止记录 token；token 轮换与失效处理接入
   `OAuthTokenManager.ensure_valid_token`。

## Consequences

- **正面**：token 不落明文、不出 API，消除生产泄漏面。
- **负面 / tradeoff**：加密密钥管理需轮换流程（否则换钥后历史数据不可解密）；
  已有明文 token 需一次性迁移加密。
- **后续约束**：新增任何凭据字段必须走加密 TypeDecorator；读接口禁止返回明文凭据。
