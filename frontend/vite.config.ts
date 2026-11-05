import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_PROXY_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target,
          changeOrigin: true,
          rewrite: (path) =>
            env.API_PROXY_STRIP_PREFIX === "false"
              ? path
              : path.replace(/^\/api/, ""),
        },
        "/ws": { target, ws: true },
        "/game/ws": { target, ws: true },
      },
    },
  };
});
