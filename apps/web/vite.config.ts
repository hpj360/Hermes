import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时 /api 代理到 FastAPI 后端（content_team/app.py 默认 127.0.0.1:8000）。
// 构建产物由 FastAPI StaticFiles 挂载。
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
