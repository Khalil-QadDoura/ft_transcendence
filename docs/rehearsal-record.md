# QA-04 team walkthrough and live-change record

Facilitator: Zayid Elkahir. [Card](https://trello.com/c/klr8xTp6).
Prepared November 26, 2026. Meeting time, college demo allowance and attendance
are unconfirmed. This is a facilitation pack; no rehearsal has been recorded.
Target: complete before the planned November 29 defense, within the November 28
18:00 Abu Dhabi sprint deadline. Use the reviewed QA-03 demo script.

## Session agenda

1. Record attendees, final commit, stack state and actual start time. Confirm the
   evaluation time allowance. Capture failures without exposing credentials.
2. Each owner gets 5–10 minutes to trace one module: user action → frontend
   component/client → API/auth check → storage/event → visible result. Explain
   one difficult choice, failure recovery, relevant tests and a real limitation.
3. Another teammate asks a question outside the presenter's prepared explanation.
   Record the question and evidence of understanding, not a blanket “passed”.
4. Each person receives an unseen small change outside their main ownership.
   Make it in a disposable practice branch, explain the change, run the relevant
   check and show the behavior. Do not push practice answers to main.
5. Run the QA-03 script with a timer. Record actual durations and failed steps.
   Assign gaps to a named pair with a deadline before defense, then repeat only
   the failed parts. End with explicit unresolved risks and the final revision.

## Facilitator exercise patterns

The exact exercise is chosen live by another teammate so it is genuinely unseen.
These are patterns, not pre-completed answers. Keep them small enough for a short
practice session; do not change authentication policy or real user data.

- Frontend owner → backend: add a bounded validation case to an existing schema
  and demonstrate the matching unit test on an isolated test database.
- Backend owner → frontend: add a localized empty-state message or accessible
  field hint, preserve the other languages, and run the relevant component check.
- Infrastructure owner → application: adjust a form's display-only helper text
  through the catalog and demonstrate English/Arabic switching.
- Any owner → documentation/test: change a game-rule example using the existing
  scoring helper and prove the expected result instead of hard-coding a score.

Success means the person can locate the responsible code, explain the trust
boundary, implement the small change, test it and interpret a failure. A generated
patch, saved study note or teammate doing the change does not establish that.

## Actual attendance and understanding (fill during the meeting)

| Person | Module / code trace | Question and answer evidence | Unseen change / practice commit | Check and observed result | Gap / partner / due |
| --- | --- | --- | --- | --- | --- |
| Zayid | Not held | Pending | Pending | Pending | To be recorded |
| Khalil | Not held | Pending | Pending | Pending | To be recorded |
| Nader | Not held | Pending | Pending | Pending | To be recorded |
| Ahmad | Not held | Pending | Pending | Pending | To be recorded |
| Burhan | Not held | Pending | Pending | Pending | To be recorded |

## Timed demo evidence

Date/time/timezone: pending. Attendees: pending. Commit: pending.
College allowance: pending. Actual start/end and elapsed: pending.
Browser names/versions and seed state: pending.

| Script segment | Actual duration | Result / evidence | Fix owner and PR | Recheck |
| --- | --- | --- | --- | --- |
| Setup/security | Not run | Pending | Pending | Pending |
| Users/profile | Not run | Pending | Pending | Pending |
| Jobs/applications/media | Not run | Pending | Pending | Pending |
| Chat/game | Not run | Pending | Pending | Pending |
| Languages/browsers | Not run | Pending | Pending | Pending |
| Monitoring/recovery | Not run | Pending | Pending | Pending |

Close QA-04 only after every person has completed the walkthrough and live
change, and each unresolved gap has a named follow-up accepted by the team.
Study material supports preparation but does not replace attendance or practice.
