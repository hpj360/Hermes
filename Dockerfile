# Hermes Knowledge Base - 多阶段构建
# Stage 1: 前端构建（node）
# Stage 2: 后端运行（python，单进程托管前端）

# ---------- Stage 1: 前端 ----------
FROM node:20-alpine AS web-builder
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- Stage 2: 后端 ----------
FROM python:3.11-slim AS runtime
WORKDIR /app

# 系统依赖（pypdf 等纯 Python，无需额外系统包；保留 curl 用于健康检查）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 安装项目（src layout）
COPY src/ ./src/
COPY README.md ./
RUN pip install --no-cache-dir -e .

# 复制前端构建产物（FastAPI StaticFiles 在 app.py 中挂载 ../web/dist）
COPY --from=web-builder /app/web/dist ./web/dist

# 运行时数据卷
VOLUME ["/app/data"]
ENV KB_DB_PATH=/app/data/hermes_kb.db
ENV KB_HOST=0.0.0.0
ENV KB_PORT=8765

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/api/health || exit 1

CMD ["hermes-kb", "serve"]
