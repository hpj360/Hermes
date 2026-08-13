# ADR 0015: content_team 引入 Alembic 迁移框架

Status: Accepted
Date: 2026-08-14

## Context

`content_team` 的数据表结构目前由 `Base.metadata.create_all` 管理（`app.py` 启动时
建表）。`create_all` 只做"表不存在则建"，**不会对已存在的表 ALTER**。一旦
`PlatformAccount` / `Topic` 等模型加列，旧 `content_team.db` 不会新增列，新代码
读旧库会报 `no such column` 或字段静默为 None。

对比：`hermes-kb` 已使用 Alembic（`alembic.ini` + `hermes-kb-migrate`），而
content_team 无迁移框架。

## Decision

1. content_team 引入 **Alembic**，废弃 `create_all` 作为 schema 管理手段。
2. 所有表结构变更通过递增迁移脚本管理；升级前强制备份 `content_team.db`。
3. 新增"旧 schema + 新代码"兼容性测试（fixture 构造旧 schema，跑新代码验证）。

## Consequences

- **正面**：表结构演进可追踪、可回滚；跨版本升级不再静默丢列。
- **负面 / tradeoff**：引入 Alembic 依赖（content_team extra 已有 sqlalchemy，加 alembic 即可）；`create_all` 移除后，全新环境需先跑 `alembic upgrade head`。
- **后续约束**：任何模型字段变更必须配套迁移脚本；禁止手工 SQL 改 schema（不可逆、无记录）。
