# Hermes Workbench 集成指南

本目录包含 Hermes Workbench 客户端 SDK，供本仓库调用 Workbench HTTP API。

## 快速开始

### 1. 启动 Workbench 服务（在 hermes-workbench 仓库）

```bash
cd hermes-workbench
hermes workbench serve --host 0.0.0.0 --port 8080
```

### 2. 在本仓库中使用客户端

#### Python

```python
# 将 workbench/ 目录加入 path 或复制 client.py 到项目内
import sys
sys.path.insert(0, "workbench")
from client import WorkbenchClient

client = WorkbenchClient("http://localhost:8080")

# 跨源查询所有 skills
skills = client.list_skills()
print(f"共 {skills['total']} 个 skills")

# 创建并运行任务
result = client.create_task(
    plan=[{"skill": "weather", "args": ["Beijing"]}],
    run=True
)

# GitHub Issues 同步
client.github_sync(repo="hpj360/Hermes")
```

#### 命令行

```bash
# 健康检查
python workbench/client.py --base-url http://localhost:8080 health

# 跨源列出 skills
python workbench/client.py skills

# 注册中心摘要
python workbench/client.py summary

# 触发 GitHub 同步
python workbench/client.py sync --repo hpj360/Hermes
```

### 3. 通过 HTTP API 直接调用（任何语言）

```bash
# curl 示例
curl http://localhost:8080/health
curl http://localhost:8080/registry/skills
curl http://localhost:8080/registry/agents
curl http://localhost:8080/registry/summary
curl -X POST http://localhost:8080/tasks \
  -H 'Content-Type: application/json' \
  -d '{"plan":[{"skill":"weather"}],"run":true}'
curl 'http://localhost:8080/github/sync?repo=hpj360/Hermes'
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| /health | GET | 健康检查 |
| /registry/sources | GET | 列出注册源 |
| /registry/skills | GET | 跨源列出 skills (?source=) |
| /registry/agents | GET | 跨源列出 agents (?source=) |
| /registry/knowledge | GET | 跨源列出知识文档 (?source=) |
| /registry/user | GET | 合并用户画像 |
| /registry/summary | GET | 注册中心摘要 |
| /skills | GET | 本地 skills |
| /skills/<name> | GET | skill 详情 |
| /memory/facts | GET/POST | facts 列表/创建 |
| /memory/facts/<key> | GET/DELETE | fact 获取/删除 |
| /memory/episodes | GET | episodes 列表 |
| /memory/profile | GET | 用户画像 |
| /tasks | GET/POST | 任务列表/创建 |
| /tasks/<id> | GET | 任务详情 |
| /tasks/<id>/run | POST | 运行任务 |
| /tasks/<id>/cancel | POST | 取消任务 |
| /github/sync | GET | GitHub Issues 同步 (?repo=&label=) |

## 客户端 SDK 特性

- **零依赖**：仅使用 Python 标准库（urllib/json）
- **单文件**：client.py 可直接复制到任何项目
- **CLI + SDK 双模式**：既可 import 也可命令行调用
- **错误处理**：WorkbenchClientError 包含 HTTP 状态码与响应体

## 自动更新

本文件由 `hermes-workbench/scripts/sync_client.py` 自动生成。
运行同步脚本可更新到最新版本:

```bash
python scripts/sync_client.py --repo hpj360/Hermes
```
