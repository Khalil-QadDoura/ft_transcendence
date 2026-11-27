import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import {
  normalize,
  validateTranslation,
} from "./legal-translation-validation.mjs";
import { fileURLToPath, URL } from "node:url";
import process from "node:process";
import console from "node:console";
const check = process.argv.includes("--check");
const manifestPath = fileURLToPath(
  new URL("../../docs/legal/translations/manifest.json", import.meta.url),
);
const packagedManifest = fileURLToPath(
  new URL("../src/features/legal/translations/manifest.json", import.meta.url),
);
const manifest = JSON.parse(
  readFileSync(
    existsSync(manifestPath) ? manifestPath : packagedManifest,
    "utf8",
  ),
);
if (existsSync(manifestPath)) {
  if (
    check &&
    normalize(readFileSync(packagedManifest, "utf8")) !==
      normalize(readFileSync(manifestPath, "utf8"))
  )
    throw new Error("Packaged legal manifest is stale");
  if (!check) {
    mkdirSync(dirname(packagedManifest), { recursive: true });
    writeFileSync(
      packagedManifest,
      normalize(readFileSync(manifestPath, "utf8")),
    );
  }
}
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
    // Frontend-only Docker builds still validate packaged translations below.
  }
  const text = normalize(
    readFileSync(existsSync(source) ? source : target, "utf8"),
  );
  if (check) {
    if (readFileSync(target, "utf8").replace(/\r\n/g, "\n") !== text)
      throw new Error(`${file} is stale: run npm run legal:sync`);
  } else writeFileSync(target, text);
  for (const language of ["ar", "az", "tr", "ru"]) {
    const translatedSource = fileURLToPath(
      new URL(
        `../../docs/legal/translations/${language}/${file}`,
        import.meta.url,
      ),
    );
    const translatedTarget = fileURLToPath(
      new URL(
        `../src/features/legal/translations/${language}/${file}`,
        import.meta.url,
      ),
    );
    if (existsSync(source) && !existsSync(translatedSource))
      throw new Error(`Missing canonical translation ${language}/${file}`);
    const translated = normalize(
      readFileSync(
        existsSync(translatedSource) ? translatedSource : translatedTarget,
        "utf8",
      ),
    );
    const errors = validateTranslation(
      text,
      translated,
      manifest.sources[file],
    );
    if (errors.length)
      throw new Error(`${language}/${file}: ${errors.join("; ")}`);
    if (check) {
      if (normalize(readFileSync(translatedTarget, "utf8")) !== translated)
        throw new Error(
          `Stale translation ${language}/${file}: run legal:sync`,
        );
    } else {
      mkdirSync(dirname(translatedTarget), { recursive: true });
      writeFileSync(translatedTarget, translated);
    }
  }
}
console.log(
  check
    ? "Legal content matches approved source."
    : "Legal build content ready.",
);
