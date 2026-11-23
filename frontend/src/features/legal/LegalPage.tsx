import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";
import { Link, useSearchParams } from "react-router-dom";
import { activeLanguage, formatDate, type Language } from "../../i18n";
import privacy from "./privacy-policy.md?raw";
import terms from "./terms-of-service.md?raw";
import sourceCopy from "../../i18n/en/legal.json";
import { translatedCopy } from "../../i18n/copy";
const copy = translatedCopy("legal", sourceCopy);
import "./legal.css";

const translations = import.meta.glob<string>("./translations/*/*.md", {
  eager: true,
  query: "?raw",
  import: "default",
});
export function legalDocument(
  kind: "privacy" | "terms",
  language: Language = "en",
) {
  const file = kind === "privacy" ? "privacy-policy.md" : "terms-of-service.md";
  const source =
    language === "en"
      ? kind === "privacy"
        ? privacy
        : terms
      : translations[`./translations/${language}/${file}`];
  if (!source)
    throw new Error(`Missing legal translation: ${language}/${file}`);
  const updated = source.match(/^Last updated: (.+)$/m)?.[1] ?? "";
  const body = source
    .replace(/^# .+\r?\n/, "")
    .replace(/^Last updated: .+\r?\n/m, "")
    .trim();
  const sections = body
    .split(/\r?\n/)
    .flatMap((line, index) =>
      line.startsWith("## ")
        ? [{ title: line.slice(3), id: `section-${index + 1}` }]
        : [],
    );
  return { body, updated, sections };
}
export function LegalPage({ kind }: { kind: "privacy" | "terms" }) {
  useTranslation("legal");
  const [params] = useSearchParams();
  const language = params.get("original") === "1" ? "en" : activeLanguage();
  const { body, updated, sections } = legalDocument(kind, language);
  const direction = language === "ar" ? "rtl" : "ltr";
  return (
    <div className="legal-page" id="legal-top">
      <header className="legal-hero">
        <p className="eyebrow">{copy.eyebrow}</p>
        <h1>{kind === "privacy" ? copy.privacyTitle : copy.termsTitle}</h1>
        <p>{copy.intro}</p>
        <p>
          {language === "en" ? copy.documentLanguage : copy.translationNotice}
        </p>
        {activeLanguage() !== "en" && (
          <Link
            className="legal-source-link"
            to={`/${kind === "privacy" ? "privacy" : "terms"}${language === "en" ? "" : "?original=1"}`}
          >
            {language === "en" ? copy.readTranslation : copy.readOriginal}
          </Link>
        )}
        <p className="legal-date">
          {copy.updated}:{" "}
          <time dateTime={updated}>
            {formatDate(new Date(`${updated}T12:00:00`), {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          </time>
        </p>
      </header>
      <div className="legal-grid">
        <nav className="legal-contents" aria-label={copy.contents}>
          <h2>{copy.contents}</h2>
          <ol lang={language} dir={direction}>
            {sections.map(({ title, id }) => (
              <li key={id}>
                <a href={`#${id}`}>{title}</a>
              </li>
            ))}
          </ol>
        </nav>
        <article className="legal-copy">
          <div lang={language} dir={direction}>
            <Markdown
              skipHtml
              components={{
                h2: ({ node, children }) => (
                  <h2
                    tabIndex={-1}
                    id={`section-${node?.position?.start.line}`}
                  >
                    {children}
                  </h2>
                ),
                a: ({ href, children }) => (
                  <a
                    href={
                      href === "privacy-policy.md"
                        ? "/privacy"
                        : href === "terms-of-service.md"
                          ? "/terms"
                          : href
                    }
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {body}
            </Markdown>
          </div>
          <div className="legal-end">
            <Link to={kind === "privacy" ? "/terms" : "/privacy"}>
              {kind === "privacy" ? copy.termsLink : copy.privacyLink}{" "}
              <span className="directional-icon" aria-hidden="true">
                ↗
              </span>
            </Link>
            <a href="#legal-top">{copy.back} ↑</a>
          </div>
        </article>
      </div>
    </div>
  );
}
