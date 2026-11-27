# FE-13: public legal pages

> November 23 FE-07 follow-up: complete AR/AZ/TR/RU reading translations now render
> with the selected locale, Arabic document direction and an English-original
> toggle. Content-owner/fluent-speaker review remains pending. See
> `docs/legal/translations/README.md` at repository root for source-hash validation
> and the canonical/packaged update process. The earlier English-only behavior
> described below is historical.

Owner: Zayid. [Card](https://trello.com/c/aOmFEclw).

`/privacy` and `/terms` are public routes inside the common layout. They render the approved DOC-01/DOC-02 Markdown with react-markdown, preserving the source update date. A section index links to stable document-line anchors. Raw HTML is skipped and the renderer's safe URL handling is retained. No user text is injected as HTML.

Canonical documents live in `docs/legal/`. `npm run legal:sync` packages copies before build; `npm run legal:check` fails CI when they drift. The frontend-only Docker build uses those checked copies. Update the canonical file, sync, and commit both. Existing source text is unchanged.

English UI keys are centralized in `copy.en.json` for FE-07. The approved documents explicitly retain `lang=en` and `dir=ltr` until reviewed translations exist. This PR does not claim translations or change legal policy.

Verify anonymous deep links, footer access, section anchors, source parity, document date, and mobile readability. The renderer is synchronous so the common route focus/title effect sees the page heading.
