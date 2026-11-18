# FE-05: password recovery and account settings

Owner: Zayid. Card: https://trello.com/c/yoNycZWb. Stacked on FE-04 #17; BE-04 #25 is merged.

Public forgot/reset pages call the shared API client. Forgot success never varies by account existence. Reset validates matching 8–128-character passwords; missing/expired links offer a fresh request. A successful reset/change clears local tokens and returns to login because Khalil revokes all token versions. Wrong current password is 400 and preserves the current session. Account deletion calls DELETE /users/me only after the shared confirmation modal; failure keeps the dialog/session available.

FE-03 schemas/validation and Ahmad’s Input/Button/Modal primitives are reused. Reset tokens stay out of logs and request referrers. The shared client owns auth/refresh/session/cache invalidation.

The settings language shortcut is pending integration of FE-06 #31. This is a dependency to complete before marking the card Done, alongside parent approval/merge and human review.

## November 11 language and review integration

Settings now includes the same five-language selector as the header. It changes document lang/dir, persists this device's preference and updates API Accept-Language without submitting password/deletion forms. Account/auth interface text is extracted into feature English resources for FE-07 translations. This supersedes the previously pending language shortcut.

PR #34 now uses `integration/FE-05-prerequisites` as its review base, combining #17 authentication and #31 localization without putting either feature into main early. **Do not merge into that integration branch.** Merge the approved parents into main, then update/retarget this PR and rerun checks. Khalil and Ahmad review the integration. Final owner practice and approval remain separate gates.
