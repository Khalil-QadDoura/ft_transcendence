# FE-03 form validation

Owner: Zayid (Frontend A). [Card](https://trello.com/c/Wp31aAQI).
This is shared validation infrastructure, not completed auth, company, job or upload screens.
Codex assisted implementation and tests; Khalil reviews the contract before merge.

## Use in a form

```tsx
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { registerSchema } from "../features/auth/schemas";
import { validationOptions } from "../lib/validation";
import { applyServerValidation } from "../lib/server-validation";

const form = useForm<
  z.input<typeof registerSchema>,
  unknown,
  z.output<typeof registerSchema>
>({
  resolver: zodResolver(registerSchema, validationOptions),
});
// After the API client returns a non-success response:
const handled = applyServerValidation(
  status,
  body,
  ["email", "password"],
  form.setError,
);
// If !handled, handle auth/network/rate-limit/structured application errors separately.
```

Use `handleSubmit` so invalid input never reaches the request callback. Inputs need visible labels, `aria-invalid`, `aria-describedby` linking the error, and an error summary/live region. Server field errors request focus. Unknown paths and malformed string details use `root.server`; render that error too. Always supply an allowlist of the form's registered fields. Do not pass paths obtained from the server into that list.

Validation messages are `validation.*` translation keys for FE-06. Pass `validationOptions` to the resolver (and direct `safeParse` calls) for structural-error fallback. The server error keeps its original text in `error.types.detail`; render that as plain React text next to the translated `validation.server` label. Never use HTML injection. Object details such as `{code: "profile_incomplete", next_step: ...}` are returned to the caller unchanged for the application guard flow. Do not treat every 422 as a field error.

For number inputs convert deliberately at the form boundary: an empty optional salary becomes `undefined`, other nonempty input becomes a number; do not use `Number("")`, which is zero. Schemas reject numeric strings, NaN and infinity. Keep raw strings for display while editing; currency precision/serialization belongs to the future API adapter. Do not trim passwords. The shared text helper counts Unicode code points like Python, so a supplementary-plane emoji is one character.

## Contract sources and ownership

| Schema            | Rules and source                                                                                                                                                                                                                                   |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auth              | BE-03 PR #8 at `2286fe4`: email normalization; register password 8–128, login only maximum 128. Browser email syntax is a broad preliminary check; Pydantic EmailStr is authoritative, including international-address policy.                     |
| Profile           | BE-05 PR #9 at `2592154`: trimmed names 1–50, position 1–100, bio ≤500; full onboarding requires birth date and age ≥18. `createProfilePatchSchema()` allows omitted fields, rejects null except bio, forbids unknown properties.                  |
| Company           | BE-21 PR #5 branch inspected on 2026-11-07: create name 1–150, optional location fields ≤100; update requires name/country/city. Country code uses that backend's supported subset and uppercases it. Ahmad owns the screens.                      |
| Job fields        | Checked-in `docs/api/api-contract.md` and reference schemas: title 1–200, location ≤150, lat ±90/lng ±180, nonnegative salary, three uppercase currency letters, schedule/salary/urgency enums. No invented salary requirement or precision limit. |
| Applications/chat | Contract/reference and pending BE-23: optional cover note ≤1000, message 1–4000, optional idempotency key ≤64. These helpers do not send messages or applications.                                                                                 |
| Media             | Card and reference contract: MP4 1–30 seconds, 1–52,428,800 bytes; JPEG/PNG/WebP avatar. Selection schemas inspect metadata and extension, not file contents. No invented avatar size cap.                                                         |

**Known integration boundaries:** BE-03 and BE-05 are still pending; this PR does not make those endpoints available. Job status is deliberately not an input to `jobFieldsSchema`: the reference transport uses `active/open`, while BE-02 uses `draft/open`. BE-22 and the screen adapter must settle that mapping. Other transport fields (tokens, object keys, reply targets, authorization) remain the owning ticket's responsibility. These are form schemas, not generated API request types.

Create the profile schema when opening/validating the form, rather than freezing a module-level “today.” The date factory accepts a Date for deterministic tests or a server-provided calendar date. The browser uses its local calendar; the server rechecks its own date, so midnight timezone differences can produce a server error. Leap-day birthdays reach the threshold on March 1 in non-leap years, matching BE-05. Video selection accepts fractional browser duration up to 30; the confirm endpoint requires integer seconds, so the upload ticket must convert/validate its confirmation payload without hiding an over-30-second selection.

Client checks improve feedback; the API must still enforce every rule, identity, permissions and actual media contents. No real credentials or uploads are used in tests.

## Verification and review

Run the standard README checks. Boundary tests exercise real schemas and the RHF integration test runs the Zod resolver, submits a valid form, maps a 422 response, renders its message and verifies focus. Browser verification uses a disposable local form harness, not an extra product route. These checks do not prove a live end-to-end API flow or translated UI; those belong to FE-04/FE-06/FE-20 and domain tickets.

The card spans seven small domain modules plus shared helpers and tests, exceeding the approximate 400-line review target. Keep the single FE-03 acceptance boundary; review primitives, domains, error adapter, then tests. Human approval, green CI and Zayid's walkthrough remain required before Done.

References: [Zod](https://zod.dev/api), [RHF Zod integration](https://react-hook-form.com/integrations/zod), [RHF setError](https://react-hook-form.com/docs/useform/seterror).
