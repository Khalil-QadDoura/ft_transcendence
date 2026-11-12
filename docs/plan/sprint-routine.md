# PM-01 — sprint routine and outstanding agreements

Owner: Zayid (@zayidelkhair / Trello @noobthinker). Updated November 11, 2026. Team timezone: Asia/Dubai (Abu Dhabi, UTC+4). [PM-01 card](https://trello.com/c/F551icOK), [PM-00 rules](https://trello.com/c/twqpeAfN), [active board](https://trello.com/b/E3788fBx/fttranscendence).

## Confirmed plan

S1: Nov 4–10; S2: Nov 11–17; S3: Nov 18–24; S4: Nov 25–28. Due dates: 18:00 Abu Dhabi at sprint end. Freeze Nov 26, then QA and rehearsal; first defense target Nov 29. The team timezone is Asia/Dubai (UTC+4); the earlier Baku label used the same offset, so no deadline moves.

Follow card → owned branch → PR → cross-pair review → green applicable CI → squash merge → Done. Review and live-change rule, set by the PO on 2026-11-08: every PR gets a review within 24 hours from someone in the other pair. After every merge, the owner makes one small live change as defense practice and records what changed and how it was checked. Keep dependency and blocking comments on the relevant card.

## Proposed weekly sync and daily update

Zayid proposes the following defaults for team confirmation. Times below use Asia/Dubai (Abu Dhabi, UTC+4).

| Routine | Proposed default | Owner / confirmation needed |
| --- | --- | --- |
| Weekly sync | Tuesday, 18:30–19:00, after the 18:00 sprint deadline; next proposed session November 17 | Zayid hosts. Team members confirm availability; the team’s WhatsApp group is the confirmed coordination channel (PO review, November 11). The call link and calendar addresses still need confirmation. |
| Daily update | Monday–Friday by 22:00 in the team’s WhatsApp group, using the template below; no routine weekend update | Zayid pins the format after the team agrees the daily cutoff. Urgent blockers stay on the card and are raised as soon as they occur. |
| Feedback on these defaults | By Monday, November 16 at 18:00 | Reply on PM-01 or PR #18 with availability and any alternative time. Zayid records the agreed result, then shares calendar invitations and pins the format. |

These are proposals, not confirmed meetings or a posted/pinned update. The next proposed session does not replace any separately agreed Sprint 1 closeout call. Zayid will record team confirmation and invitation links here before checking those acceptance items.

## Ready-to-pin daily update template

```text
Date / name
Done: CARD-ID — concrete result + PR or evidence link
Next: CARD-ID — next reviewable outcome
Blocked: CARD-ID — dependency, owner and the decision/help needed (or None)
```

## Weekly 30-minute agenda

- 0–5 min: review completed and merged work against the board.
- 5–15 min: resolve blockers and backend/frontend contract questions.
- 15–25 min: agree next sprint scope and capacity; owners join their cards.
- 25–30 min: record decisions, review requests and actions with owners.

## Open actions and integration handoffs

| Action | Owner | Completion evidence |
| --- | --- | --- |
| Authorize the GitHub Power-Up repository connection for `Khalil-QadDoura/ft_transcendence` | Khalil (@Khalil-QadDoura), repository admin | Connected repository visible in the Power-Up; Zayid checks that a linked PR shows repository details on its card. |
| Confirm the recurring slot, call link and calendar recipients | Zayid, with all five team members | Recorded agreement and calendar invitations. |
| Confirm the daily cutoff, then pin the template in the team’s WhatsApp group | Zayid, with the team | Recorded cutoff agreement and a link to the pinned WhatsApp update. |
| Review the shared API client and auth-screen integration | Ahmad (FE-20) and Zayid (FE-04); Khalil reviews the backend contract | FE-20 [PR #22](https://github.com/Khalil-QadDoura/ft_transcendence/pull/22) and FE-02 [PR #2](https://github.com/Khalil-QadDoura/ft_transcendence/pull/2) are merged. FE-04 [PR #17](https://github.com/Khalil-QadDoura/ft_transcendence/pull/17) integrates the shared client, targets main, and awaits renewed review; its local test suite passed November 11. |
| Review shared UI primitives | Ahmad (FE-21), cross-pair reviewer | FE-21 [PR #21](https://github.com/Khalil-QadDoura/ft_transcendence/pull/21) is merged; new screens should reuse the shared components. |

BE-02 and corrected BE-03 are merged on main; frontend integration uses the current team backend contract. Card comments record any further API mismatch with the responsible owner.

## Acceptance record

| PM-01 item | Current state / required evidence |
| --- | --- |
| GitHub Power-Up enabled and repo linked | Official GitHub Power-Up enabled November 8; PR #18 is attached to PM-01. On November 10 the card still says “See more details when you connect to GitHub”; repository authorization by Khalil remains pending. An attached PR link alone does not complete the connection. |
| Weekly sync agreed and in every calendar | Concrete Tuesday 18:30 proposal above; team confirmation, call details and calendar invitations pending. |
| Daily format pinned in the team chat | Template and weekday 22:00 proposal above; WhatsApp confirmed by the PO on November 11; cutoff agreement and pin evidence pending. |
| Overview board URL and decisions reconciled | PM-00 plan is merged through PR #12. This PR preserves the INF-01 front-proxy decision, corrects the schedule timezone and links this routine; updated head awaits PO review and merge. |
| Every member joined Sprint 1 cards | Verified November 8 from live board member badges and card Members sections; all 23 original S1 cards had their owners attached (historical table below). |

## Sprint 1 membership audit — November 8, 2026

| Owner / Trello identity | Cards with owner membership observed |
| --- | --- |
| Khalil / khalilkaddoura | BE-01, BE-02, BE-03, BE-05 |
| Nader / naderkhalil2 | BE-20, BE-21, BE-23 |
| Zayid / noobthinker | FE-01, FE-02, FE-03, FE-04, PM-00, PM-01 |
| Ahmad / ahmadradwan | FE-20, FE-21 |
| Burhan / byulbyul | DOC-08, DOC-03, INF-01, INF-02, INF-03, INF-04, INF-05, INF-06 |

Membership does not establish completion, authorship or review approval. PM-00 stays as the reference card at the top of To Do. DOC-01 and DOC-02 were also visible in Review during the membership audit; they are not included in the original 23-card S1 count.

PM-01 remains In Progress until the repository connection, calendar agreement and pinned daily update are complete. The communication channel itself is confirmed: the team’s WhatsApp group.
