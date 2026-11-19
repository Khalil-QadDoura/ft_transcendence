import { defineConfig } from "vitest/config";

// `npm run rules:check` (FE-34): compares the rules page's numbers and worked
// examples with docs/game/turing-duel-rules.md. Kept out of `npm test` because
// `make test` builds the frontend with ./frontend as the Docker context, where
// ../docs does not exist; the CI frontend job runs it from a full checkout.
export default defineConfig({
  test: {
    environment: "node",
    include: ["scripts/game-rules.drift.ts"],
  },
});
