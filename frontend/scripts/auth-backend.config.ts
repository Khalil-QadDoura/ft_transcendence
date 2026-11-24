import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: [
      "scripts/auth-backend.integration.ts",
      "scripts/social-backend.integration.ts",
    ],
    fileParallelism: false,
    testTimeout: 30_000,
  },
});
