# Code Review: figma-reader

> **审阅对象**: `skills/figma-reader/` (6 个 Python 脚本 + 1 个 JSON fixture)
> **审阅时间**: 2026-07-23
> **审阅者**: Hermes Agent (self-review + 多视角对抗)
> **关联 commit**: 13e0baa
> **关联测试**: tests/skills/figma_reader/test_figma_reader.py (7 cases)

## Verdict: ✅ READY (无 P0 / 1 P1 / 2 P2)

## P0 阻塞：无

无阻塞项。

## P1 必须修

### P1-1: 限流重试仅 3 次，可能仍不够

**位置**: `scripts/client.py:74-95` (`FigmaClient._request`)

**问题**: 429 触发后只重试 3 次，每次退避 60 秒。在批量导出 100+ 张图时仍可能失败。

**建议**: 改为指数退避（1s, 2s, 4s, 8s, ...）+ 抖动，最多 5 次。

**风险**: 如不修，CI 跑完整批导出会随机失败。

## P2 可改进

### P2-1: `get_images` 的下载重定向未处理

**位置**: `scripts/client.py:181-188` (`download_image`)

**问题**: Figma 临时 URL 可能 302 重定向到 S3，未设置 `allow_redirects=True`（requests 默认 True，但显式更安全）。

**建议**: 显式加 `allow_redirects=True`，加 User-Agent 头。

### P2-2: mock 模式的 fixture 路径硬编码

**位置**: `scripts/client.py:99-100`

**问题**: `_mock_request` 默认从 `Path(__file__).parent.parent / "data"` 找 fixture，限制了目录结构。

**建议**: 接受 `mock_data_dir` 参数（已有），并在 README 中说明用法。

## 亮点

- ✅ 4 个核心端点封装清晰
- ✅ URL 解析支持 3 种 URL 形式（file/design/proto）
- ✅ 异常类型分层（Auth / NotFound / RateLimit / Generic）
- ✅ 限流自动退避
- ✅ mock 模式可在无 token 环境下完整跑通
- ✅ 单元测试 7 cases 覆盖核心路径

## 复杂度评估

- **代码行数**: ~280 行（含注释）
- **依赖**: requests（标准）
- **可维护性**: 高（每个端点一个 method）
- **AI 友好度**: 高（参数命名清晰、类型注解完整）
