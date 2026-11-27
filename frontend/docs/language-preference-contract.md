# FE-07 account language — deferred until after defense

Owner: Zayid Elkahir, frontend. Backend owner/reviewer: Khalil.
Proposed on November 23 in [PR #93](https://github.com/Khalil-QadDoura/ft_transcendence/pull/93#issuecomment-7100391111).

Current behavior remains local storage plus `Accept-Language`. Khalil's review
confirmed that browser persistence is sufficient for the defense in his review of
PR #93 at 0c34871. Account persistence is a follow-up, not a current merge blocker.
`UserOut` has no language field and
`UserUpdate` rejects extra fields; the frontend must not send a speculative PATCH.

## Proposed API

- Nullable `language` on the user and `UserOut`: `en`, `ar`, `az`, `tr`, `ru` or null.
- Existing users migrate to null, preserving their current device preference.
- `PATCH /api/users/me` accepts a supported language, leaves it unchanged when
  omitted, clears the preference with null and rejects unsupported values.
- GET returns only the authenticated user's preference. Existing auth, rate
  limits, validation and other profile fields retain their behavior.

## Frontend behavior after the contract lands

- Restore the authenticated user's non-null preference once per session; a null
  preference retains the current device selection.
- Guest changes stay local. Explicit authenticated changes update the interface
  immediately and save to the account; hydration must not trigger a write loop.
- A failed save keeps the selected interface language, announces that account
  saving failed and offers retry. It must not clear auth or revert entered forms.
- Rapid switches must serialize/coalesce writes so the last choice wins.
- A response from a previous session must not change the next user's interface.
- Test reload and a second browser/device, omitted/null/invalid PATCH, failed save,
  rapid changes and account switching against the real backend contract.

This is a reviewable proposal, not an implemented backend endpoint or a claim of
cross-device persistence. Implement the frontend adapter after Khalil confirms
the contract and supplies the backend change.
