import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Frontend は `/api` への相対 fetch だけを行い、backend への到達は
// proxy が担う。dev (`vite`) は server.proxy、preview / Docker 配信
// (`vite preview`) は preview.proxy が必要なため、両方に同じ設定を入れる。
// preview.proxy を入れないと docker-compose の frontend から /api が
// backend へ届かず 404 になる。
const backendTarget = process.env.VITE_BACKEND_URL ?? "http://backend:8000";
const apiProxy = {
  "/api": {
    target: backendTarget,
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "src/vite-env.d.ts", "src/main.tsx"],
      thresholds: {
        statements: 70,
        branches: 65,
        functions: 70,
        lines: 70,
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
    proxy: apiProxy,
  },
});
