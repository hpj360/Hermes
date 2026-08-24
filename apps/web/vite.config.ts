import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时 /api、/wb、/feishu 代理到统一网关（hermes.workbench.gateway，默认 127.0.0.1:8000）。
// 构建产物由网关 StaticFiles 挂载（同一进程既出 API 又出 GUI）。
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/wb": "http://127.0.0.1:8000",
      "/feishu": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
