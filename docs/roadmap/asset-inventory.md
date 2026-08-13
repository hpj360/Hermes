# 资产盘点报告（阶段 0.3）

> 日期：2026-08-14
> 目的：在"六仓归一"启动前，记录 6 份引擎拷贝的现状，作为收敛基线与回滚锚点。

---

## 一、六仓清单

### 1.1 四个 git 仓

| 仓 | 路径 | 包名 | 版本 | skill 数 | 本质 |
|---|---|---|---|---|---|
| hermes | `D:\Hermes\hermes` | `hermes` | 0.6.0 | 44 | 引擎主仓（唯一可信源） |
| content-team | `D:\Hermes\content-team` | `hermes`（冒名） | 0.6.0 | 21 | 引擎 fork + content_team 业务 |
| hermes-kb | `D:\Hermes\hermes-kb\hermes-knowledge-base` | `hermes`（冒名） | 0.6.0 | — | 引擎 fork + `hermes_backup_v050` + `hermes_kb` RAG |
| Hermes-workbench | `D:\Hermes\Hermes-workbench\hermes-workbench-` | `hermes`（冒名） | 0.4.0 | 70 | 引擎 fork + PM Framework |

### 1.2 三个临时目录（已授权删除）

| 目录 | HEAD | 工作树 | 结论 |
|---|---|---|---|
| `hermes-temp` | `60d2a29 feat: MemOS 融合` | 干净 | 旧 clone，无独特提交，删除安全 |
| `hermes-tmp` | `60d2a29 feat: MemOS 融合` | 干净 | 同上 |
| `tmp_hermes` | `60d2a29 feat: MemOS 融合` | 1 个未提交改动（skills/code-review/SKILL.md） | 同上（改动已在主仓体现） |

> 三目录均无 `.state` / `.env`（无运行时数据、无敏感配置），`src/` 落后主仓
> （缺 `content_team`、`cli_skill_market.py`），确认是迭代开始前的快照副本。

---

## 二、分叉差异（关键资产漂移）

### 2.1 content_team（业务模块）分叉

- hermes 主仓的 `src/hermes/content_team/` 比 content-team 仓**更新**：
  - 仅存在于 hermes 主仓的 4 个文件：`auth/oauth_flow.py`、`auth/__init__.py`、
    `publish/adapters/wechat_video.py`、`analytics/adapters.py`
  - 两仓有 13 个文件内容不同
- **结论**：引擎仓在给业务模块加功能，边界与现实相反。M3 合并时需先 diff 收敛，
  否则丢 `auth/` + `wechat_video` 两个已实现能力。

### 2.2 PM Framework（workbench 独有资产）

- workbench 70 skill，来源三分（`manifest.json` 的 `skillProvenance`）：
  - `pm-framework@3.0.0`：24 个（**只存在于 workbench**，需上收 hermes）
  - `hermes-original`：33 个（与 hermes 重叠，会 drift）
  - `hermes-upstream@0.6.0`：13 个
- workbench 另有 `agents/` 下 4 个 agent 定义（director / requirement-analyst /
  backend-developer / tester），hermes 主仓无 `agents/`。

### 2.3 hermes-kb 内嵌引擎

- `src/` 下含三份：`hermes`（引擎 fork）、`hermes_backup_v050`（备份引擎）、
  `hermes_kb`（RAG 后端）。需剥离前两份。

---

## 三、回滚锚点（tag 计划）

已对 4 个 git 仓打 `pre-converge` tag：
- [x] hermes
- [x] content-team
- [x] hermes-kb
- [x] Hermes-workbench

---

## 四、临时目录删除记录

- [x] `hermes-temp` 已删除
- [x] `hermes-tmp` 已删除
- [x] `tmp_hermes` 已删除
