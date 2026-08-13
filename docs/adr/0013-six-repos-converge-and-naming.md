# ADR 0013: 六仓归一 + 包命名方案（hermes 唯一，其他去冒名）

Status: Accepted
Date: 2026-08-14

## Context

项目在磁盘上存在 **4 个引擎拷贝 + 3 个临时目录**（六仓）：

| 仓 | 包名（pyproject） | 本质 |
|---|---|---|
| `hermes` | `hermes` 0.6.0 | 引擎主仓（唯一可信源） |
| `content-team` | `hermes` 0.6.0 | 引擎完整 fork + content_team 业务 |
| `hermes-kb` | `hermes` 0.6.0 | 引擎 fork + `hermes_backup_v050` + `hermes_kb` RAG |
| `Hermes-workbench` | `hermes` 0.4.0 | 引擎 fork + PM Framework（70 skill） |
| `hermes-temp`/`hermes-tmp`/`tmp_hermes` | — | 临时副本（已删除） |

四个仓 **同名 `hermes`**，导致 `pip install hermes` 语义不明（无法自依赖、不知道装谁），且 content_team / PM Framework 代码三处 drift。

## Decision

1. **`hermes` 保持唯一包名**（引擎主仓），是 `pip install hermes` 的唯一合法源。
2. **其他仓"去冒名"**：
   - content-team 剥离引擎代码后，业务包改名 `content-team`，依赖 `hermes`。
   - hermes-kb 剥离 `src/hermes` 与 `src/hermes_backup_v050`，RAG 包改名 `hermes-kb`。
   - workbench- 不再发布 pip 包，只做 Docker 发行薄壳。
3. **唯一资产信源**：skills / knowledge 只在 hermes；PM Framework 资产上收（见 ADR-0014）。
4. **依赖方向单向无循环**：`content-team →(pip) hermes`，`hermes →(HTTP) hermes-kb`，`workbench- →(镜像) hermes`。
5. **稳定公开 API**：下游只依赖 `hermes.workbench` 公开接口，不 import 引擎私有实现。

## Consequences

- **正面**：`hermes` 包名唯一，pip 语义清晰；消除四份引擎 drift；现有 `pip install hermes` + `hermes` CLI 零影响（hermes 不改名）。
- **负面 / tradeoff**：其他三仓需一次性改名 + 剥离引擎代码（大动作，分阶段）；下游包名变更需同步更新引用。
- **后续约束**：任何新 fork 不得再声明 `name="hermes"`；新增下游必须以依赖而非 copy 的方式接入。
