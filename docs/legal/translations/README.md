# Legal reading translations — November 23, 2026

Owner: Zayid Elkahir (FE-07 / FE-08). Content owner: Burhan.

The Arabic, Azerbaijani, Turkish and Russian folders contain complete reading
translations of both canonical English documents in `docs/legal/`. All 11 privacy
sections and 13 terms sections, lists, retention periods, contacts and external
processing disclosures are retained. These are translations, not changes to the
English policy. Fluent-speaker and content-owner approval is **pending** for all
four languages; `manifest.json` records that status without implying approval.

The legal pages follow the selected language, with Arabic `lang` and `dir` on the
document and table of contents. They show a review-pending notice and offer the
unchanged English document through `?original=1`, plus a return-to-translation
link. The original policy date remains the document date; translation date is
recorded separately in the manifest.

## Updating a document

1. Edit the canonical English source and every affected translation together.
2. Compare meaning and all obligations, exceptions, durations, recipients and
   rights. Obtain content-owner and fluent-speaker review; do not treat a passing
   structural check as semantic approval.
3. Update the manifest's normalized SHA-256 source hash only after reconciling
   translations with the changed source. Record the actual review status.
4. Run `npm run legal:sync` from `frontend`, then `npm run legal:check`. Commit
   canonical documents, manifest and packaged copies together.

CI checks source hashes, dates, section numbers, subsection/list counts, contacts,
links, damaged replacement characters and packaged-copy drift. A changed English
source fails validation until the translation manifest is deliberately reconciled.
The frontend-only container also checks its packaged documents against that hash.
These checks cannot certify wording or legal equivalence.
