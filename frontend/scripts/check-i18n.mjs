import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { fileURLToPath, URL } from "node:url";
import console from "node:console";
import process from "node:process";
const root = fileURLToPath(new URL("../", import.meta.url));
import { validateMessages } from "./i18n-validation.mjs";
const plan = JSON.parse(
  readFileSync(join(root, "src/i18n/translation-plan.json"), "utf8"),
);
let failed = false;
for (const namespace of readdirSync(join(root, "src/i18n/en")).filter((name) =>
  name.endsWith(".json"),
)) {
  const source = JSON.parse(
    readFileSync(join(root, "src/i18n/en", namespace), "utf8"),
  );
  for (const language of ["ar", "az", "tr", "ru"]) {
    if (
      plan.englishFallbackNamespaces[namespace.replace(".json", "")]?.includes(
        language,
      )
    ) {
      console.warn(`Temporary English fallback: ${language}/${namespace}`);
      continue;
    }
    const target = join(root, "src/i18n", language, namespace);
    try {
      const translated = JSON.parse(readFileSync(target, "utf8"));
      const errors = validateMessages(source, translated, language);
      if (errors.length) {
        console.error(`${language}/${namespace}: ${errors.join(", ")}`);
        failed = true;
      }
    } catch {
      console.error(`Cannot read ${target}`);
      failed = true;
    }
  }
}
// Gate production JSX text. Dev-only component fixtures and fixed brand names are excluded.
// Approved legal Markdown stays unchanged until reviewed translations exist.
let literals = 0;
function scan(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const file = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (relative(root, file).replaceAll("\\", "/") !== "src/features/dev")
        scan(file);
    } else if (file.endsWith(".tsx") && !file.includes(".test.")) {
      const source = ts.createSourceFile(
        file,
        readFileSync(file, "utf8"),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX,
      );
      function visit(node) {
        if (
          (ts.isJsxText(node) &&
            /[\p{L}]/u.test(node.text.trim()) &&
            !/^(wozu|WOZU|WOZU ✳)$/.test(node.text.trim())) ||
          (ts.isJsxAttribute(node) &&
            /^(placeholder|title|aria-label|alt)$/.test(
              node.name.getText(source),
            ) &&
            node.initializer &&
            ts.isStringLiteral(node.initializer))
        ) {
          literals++;
          failed = true;
          const line =
            source.getLineAndCharacterOfPosition(node.getStart(source)).line +
            1;
          console.error(
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
  `Translation keys: ${failed ? "FAIL" : "PASS"}; ${literals} unextracted production JSX literals.`,
);
if (failed) process.exitCode = 1;
