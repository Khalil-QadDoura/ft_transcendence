import process from "node:process";
import { spawnSync } from "node:child_process";
import { loadEnv } from "vite";
const env = loadEnv("development", process.cwd(), "");
const source =
  process.argv[2] ||
  env.OPENAPI_URL ||
  "http://127.0.0.1:5174/api/openapi.json";
const result = spawnSync(
  process.execPath,
  [
    "node_modules/openapi-typescript/bin/cli.js",
    source,
    "-o",
    "src/api/schema.d.ts",
  ],
  { stdio: "inherit" },
);
if (result.error) throw result.error;
process.exit(result.status ?? 1);
