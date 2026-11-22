import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["scripts/employer-backend.integration.ts"],
    testTimeout: 30_000,
  },
});
