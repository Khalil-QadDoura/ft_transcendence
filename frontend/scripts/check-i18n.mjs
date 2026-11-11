import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { fileURLToPath, URL } from "node:url";
import console from "node:console";
import process from "node:process";
const root = fileURLToPath(new URL("../", import.meta.url));
const keys = (value, prefix = "") =>
  Object.entries(value).flatMap(([key, child]) =>
    typeof child === "object" && child !== null
      ? keys(child, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
let failed = false;
for (const namespace of readdirSync(join(root, "src/i18n/en")).filter((name) =>
  name.endsWith(".json"),
)) {
  const source = keys(
    JSON.parse(readFileSync(join(root, "src/i18n/en", namespace), "utf8")),
  );
  for (const language of ["ar", "az", "tr", "ru"]) {
    const target = join(root, "src/i18n", language, namespace);
    try {
      const translated = keys(JSON.parse(readFileSync(target, "utf8")));
      const missing = source.filter((key) => !translated.includes(key));
      if (missing.length) {
        console.error(
          `${language}/${namespace}: missing ${missing.join(", ")}`,
        );
        failed = true;
      }
    } catch {
      console.error(`Cannot read ${target}`);
      failed = true;
    }
  }
}
// Report existing literals for FE-07. Key parity above is the CI gate; this report is a migration inventory.
let literals = 0;
function scan(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const file = join(dir, entry.name);
    if (entry.isDirectory()) scan(file);
    else if (file.endsWith(".tsx") && !file.includes(".test.")) {
      const source = ts.createSourceFile(
        file,
        readFileSync(file, "utf8"),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX,
      );
      function visit(node) {
        if (
          (ts.isJsxText(node) && /[\p{L}]/u.test(node.text.trim())) ||
          (ts.isJsxAttribute(node) &&
            /^(placeholder|title|aria-label|alt)$/.test(
              node.name.getText(source),
            ) &&
            node.initializer &&
            ts.isStringLiteral(node.initializer))
        ) {
          literals++;
          const line =
            source.getLineAndCharacterOfPosition(node.getStart(source)).line +
            1;
          console.warn(
            `${relative(root, file)}:${line}: JSX text needs translation: ${node.getText(source).trim().slice(0, 90)}`,
          );
        }
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
}
scan(join(root, "src"));
console.log(
  `Translation keys: ${failed ? "FAIL" : "PASS"}; ${literals} JSX literals flagged for FE-07.`,
);
if (failed) process.exitCode = 1;
