import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: "127.0.0.1",
      port: 5174,
      strictPort: true,
      proxy: {
        "/api": {
          target: env.API_PROXY_TARGET || "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (path) =>
            env.API_PROXY_STRIP_PREFIX === "true"
              ? path.replace(/^\/api/, "")
              : path,
        },
        "/ws": {
          target: env.API_PROXY_TARGET || "http://127.0.0.1:8000",
          ws: true,
          changeOrigin: true,
        },
      },
    },
  };
});
