# PM-01 — sprint routine and outstanding agreements

Owner: Zayid (@zayidelkhair / Trello @noobthinker). Updated November 8, 2026 (America/Los_Angeles), with Codex assistance. [PM-01 card](https://trello.com/c/F551icOK), [PM-00 rules](https://trello.com/c/twqpeAfN), [active board](https://trello.com/b/E3788fBx/fttranscendence).

## Confirmed plan

S1: Nov 4–10; S2: Nov 11–17; S3: Nov 18–24; S4: Nov 25–28. Due dates: 18:00 Baku at sprint end. Freeze Nov 26, then QA and rehearsal; first defense target Nov 29. These dates do not establish a weekly meeting time.

Follow card → owned branch → PR → cross-pair human review → green CI → squash merge → Done. Keep dependency and blocking comments on the relevant card. A review request is not approval, and a working local prototype is not a merged ticket.

## Questions for the team

1. Which day and time can all five people attend a weekly 30-minute sync? Should the calendar use Asia/Baku? Tuesday evening is only the card's suggestion, not an agreement.
2. Who should host, what meeting link should we use, and which calendar addresses should receive the invitation?
3. Which team chat/channel will hold the pinned daily update? What is the daily cutoff, in which timezone, and do we update on weekends?
4. Ahmad: when can FE-20's shared client land, and what auth interface should FE-04 call for token storage, refresh and logout? FE-21's shared primitives also need an integration date.
5. Khalil: should frontend integration target the fixed BE-03 branch until it merges, and what is the expected API contract after its dependent PRs are rebased?
6. Has everyone joined their own Sprint 1 cards and attached each PR? Report blocked dependencies rather than marking incomplete work Done.

Zayid confirmed on November 8 that the meeting time and chat details are not known yet. Do not invent agreement, send calendar invitations, or claim a pinned message until the team answers and the actual destination is known.

## Ready-to-pin daily update template

```text
Date / name
Done: CARD-ID — concrete result + PR or evidence link
Next: CARD-ID — next reviewable outcome
Blocked: CARD-ID — dependency, owner and the decision/help needed (or None)
```

## Suggested 30-minute agenda (pending team agreement)

- 0–5 min: review completed and merged work against the board.
- 5–15 min: resolve blockers and backend/frontend contract questions.
- 15–25 min: agree next sprint scope and capacity; owners join their cards.
- 25–30 min: record decisions, review requests and actions with owners.

## Acceptance record

| PM-01 item | Current state / required evidence |
| --- | --- |
| GitHub Power-Up enabled and repo linked | Official Trello Inc GitHub Power-Up enabled November 8; directory shows Enabled 1 and Settings. Target repository connection remains pending account authorization. Ordinary PR links are not proof of a connected Power-Up. No new GitHub OAuth access grant was approved. |
| Weekly sync agreed and in every calendar | Pending team agreement and verified invitations; no invitations sent. |
| Daily format pinned in the team chat | Template prepared above; channel and cutoff pending, nothing posted or pinned. |
| Overview board URL and decisions reconciled | Implemented in this PR from PM-00/PM-01 and merged BE-02 evidence; requires review/merge. |
| Every member joined Sprint 1 cards | Verified November 8 from live board member badges and card Members sections; all 23 original S1 cards have their owners attached (table below). |

## Sprint 1 membership audit — November 8, 2026

| Owner / Trello identity | Cards with owner membership observed |
| --- | --- |
| Khalil / khalilkaddoura | BE-01, BE-02, BE-03, BE-05 |
| Nader / naderkhalil2 | BE-20, BE-21, BE-23 |
| Zayid / noobthinker | FE-01, FE-02, FE-03, FE-04, PM-00, PM-01 |
| Ahmad / ahmadradwan | FE-20, FE-21 |
| Burhan / byulbyul | DOC-08, DOC-03, INF-01, INF-02, INF-03, INF-04, INF-05, INF-06 |

Membership does not establish completion, authorship or review approval. PM-00 stays as the reference card at the top of To Do. DOC-01 and DOC-02 were also visible in Review; they are not included in the original 23-card S1 count above.

This documentation completes the reviewable repository portion of PM-01. The operational ticket remains In Progress until the real agreements, links and membership evidence exist. Historical dates and teammates' contributions must remain accurate.
