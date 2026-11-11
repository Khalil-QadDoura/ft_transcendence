import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import process from "node:process";
import console from "node:console";
const check = process.argv.includes("--check");
for (const file of ["privacy-policy.md", "terms-of-service.md"]) {
  const source = fileURLToPath(
    new URL(`../../docs/legal/${file}`, import.meta.url),
  );
  const target = fileURLToPath(
    new URL(`../src/features/legal/${file}`, import.meta.url),
  );
  if (!existsSync(source)) {
    if (check) throw new Error(`Canonical legal source missing: ${source}`);
    if (!existsSync(target))
      throw new Error(`Packaged legal source missing: ${target}`);
    continue; // frontend-only Docker context uses the copies checked in CI.
  }
  const text = readFileSync(source, "utf8").replace(/\r\n/g, "\n");
  if (check) {
    if (readFileSync(target, "utf8").replace(/\r\n/g, "\n") !== text)
      throw new Error(`${file} is stale: run npm run legal:sync`);
  } else writeFileSync(target, text);
}
console.log(
  check
    ? "Legal content matches approved source."
    : "Legal build content ready.",
);
