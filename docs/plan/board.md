# ft\_transcendence — Trello Board

Nov 4, 2026 · @byul-byul

How the Trello board works: lists, sprints, card IDs, card structure, assignment and labels. The full card list as of 2026-11-04 is in [backlog.md](backlog.md); decisions and the module plan are in [overview.md](overview.md).

## Board

- Board: https://trello.com/b/E3788fBx/fttranscendence
- The old board (`6Pob02M6`) is no longer used; nobody changes it. Cards that existed before the 2026-11-04 setup were moved to Done.
- PM-01 connects the GitHub Power-Up so PRs and commits can appear on cards. As verified November 8, the Power-Up is enabled; repository authorization/linking is still pending. Ordinary PR links do not establish that connection.

| Person | Trello member | Role(s) |
| --- | --- | --- |
| byul-byul | byulbyul | Product Owner + Developer (DevOps) |
| Khalil | khalilkaddoura | Tech Lead / Architect + Developer (Backend A) |
| Nader | naderkhalil2 | Developer (Backend B) |
| Zayid | noobthinker | PM / Scrum Master + Developer (Frontend A) |
| Ahmad | ahmadradwan | Developer (Frontend B) |

## Lists and card flow

Every card travels **Backlog → To Do → In Progress → Review → Done**, and every change travels card → branch → PR → review → merge → card moved, so the board and the Git history tell the same story at the defense.

| List | Holds | Moves in when |
| --- | --- | --- |
| Backlog | Every card not in the current sprint, ordered S2, S3, S4, then tier C (TC). byul-byul (PO) keeps the order | — |
| To Do | The current sprint. Zayid (PM) runs it | The sprint starts |
| In Progress | Cards being worked on | The owner starts work and opens the branch |
| Review | Cards with an open PR | The PR is ready; a reviewer from the other pair reviews it |
| Done | Finished cards | The PR is merged and every "Done when" item is ticked, including "Definition of Done met (PM-00)" |

PM-00 is the reference card: keep it at the top of To Do. It has no sprint deadline or completion checklist; its documentation can be merged without moving the reference card to Done.

## Sprints and key dates

The counts below preserve the November 4 planning snapshot; consult Trello for current status. One sprint per week; S4 is four days. Card due date = sprint end, 18:00 Asia/Baku.

| Sprint | Dates | Card due date | Cards |
| --- | --- | --- | --- |
| S1 | Nov 4–10 | Nov 10, 18:00 | 23 (list To Do) |
| S2 | Nov 11–17 | Nov 17, 18:00 | 28 |
| S3 | Nov 18–24 | Nov 24, 18:00 | 27 |
| S4 | Nov 25–28 | Nov 28, 18:00 | 12 |
| Backlog, sprint per due date | — | as set on the card | 2 (BE-33, FE-36) |
| Tier C | — | none | 5 (TC-01 … TC-05) |

| Date | Event |
| --- | --- |
| Sun Nov 22 | Tier C check: TC cards start only if core + tier B are on track |
| Thu Nov 26 | Code freeze |
| Sun Nov 29 | First defense |

Maximum score has priority over the defense date.

## Card IDs, branches and commits

The card ID is the prefix of the card title, e.g. `BE-07 Port intro video upload, confirm, post/unpost/delete and feed`.

| Prefix | Area |
| --- | --- |
| `INF` | Infrastructure / DevOps |
| `BE` | Backend |
| `FE` | Frontend |
| `DOC` | Documentation: README, legal pages, game rules |
| `PM` | Project management |
| `QA` | Testing and defense rehearsal |
| `TC` | Tier C modules (only if ahead of schedule) |

- Branch: `feat/<CARD-ID>-<short-name>`, e.g. `feat/BE-07-intro-video`; other change types use the same pattern (`fix/BE-10-vote-room-check`, `docs/PM-00-board-docs`).
- Commit message (from [overview.md](overview.md#ways-of-working)): `<type>(<scope>): <summary> (<CARD-ID>)`, types `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`. Example: `feat(game): reject votes for participants of other rooms (BE-10)`.
- One card per PR.

## Card structure

```markdown
BE-07 Port intro video upload, confirm, post/unpost/delete and feed

Owner: Khalil
<description>

Done when:
- [ ] <acceptance criterion>
- [ ] ...
- [ ] Definition of Done met (PM-00)
```

- First line of the description: `Owner: <name>`.
- "Done when" checklist; its last item is always "Definition of Done met (PM-00)". Card PM-00 (Zayid) defines the Definition of Done.
- Due date = sprint end, 18:00 Asia/Baku; tier C cards have no due date.
- Labels: at least one track label, plus module, Mandatory and priority labels where they apply (see Labels).
- Dependencies are listed per card in [backlog.md](backlog.md).

## Assignment

- Every card has exactly one owner, named on the `Owner:` line.
- The Trello member on the card must match the `Owner:` line.
- Members join their own cards. During the 2026-11-04 setup byul-byul assigns every card to its owner manually, because the Trello connector used to create the cards cannot assign members.
- Cross-track help is planned on the board, not ad hoc: Nader owns FE-14 and FE-31, byul-byul owns FE-34 (the frontend is the critical path).

## Labels

| Label | Color | Meaning |
| --- | --- | --- |
| Backend | green | Track: backend work |
| Frontend | blue | Track: frontend work |
| DevOps | orange | Track: infrastructure work |
| Docs | sky | Track: documentation and process work |
| Security | red | Secondary: the card touches security |
| Database | purple | Secondary: the card touches the database (schema, seed, backups) |
| M1 … M20 | grey (`black_light`) | The subject module the card serves (mapping below) |
| Mandatory | `lime_dark` | Mandatory subject requirement; the project is rejected without it |
| P1 | `pink_dark` | Blocks other cards or the defense |
| P2 | `pink_light` | Important but not blocking |
| Bug | `red_dark` | Defect found later |

The labels "Major module" and "Minor module" exist on the board but are not used; the module type is in the table below. PM-00 is the only card without a priority label.

**Module labels**

| Label | Module | Type | Pts | Plan | Cards |
| --- | --- | --- | --- | --- | --- |
| M1 | Frameworks for frontend and backend | Major | 2 | Core | 3 |
| M2 | Real-time features (WebSockets) | Major | 2 | Core | 5 |
| M3 | User interaction: chat, profile, friends | Major | 2 | Core | 7 |
| M4 | Standard user management | Major | 2 | Core | 7 |
| M5 | ORM | Minor | 1 | Core | 2 |
| M6 | Advanced search: filters, sorting, pagination | Minor | 1 | Core | 3 |
| M7 | Web-based game | Major | 2 | Core | 8 |
| M8 | Multiplayer game, 3+ players | Major | 2 | Core | 5 |
| M9 | Content moderation AI | Minor | 1 | Core | 4 |
| M10 | Multiple languages (3+) | Minor | 1 | Core | 2 |
| M11 | Right-to-left language support | Minor | 1 | Core | 1 |
| M12 | Monitoring with Prometheus + Grafana | Major | 2 | Core | 4 |
| M13 | WAF / ModSecurity + HashiCorp Vault | Major | 2 | Tier B | 4 |
| M14 | Health check, status page, automated backups, recovery | Minor | 1 | Tier B | 5 |
| M15 | OAuth 2.0 (42 intra) | Minor | 1 | Tier B | 1 |
| M16 | Additional browsers (Firefox, Safari or Edge) | Minor | 1 | Tier B | 1 |
| M17 | AI Opponent | Major | 2 | Tier C | 1 |
| M18 | Remote players | Major | 2 | Planned (added 2026-11-04) | 4 |
| M19 | GDPR compliance | Minor | 1 | Tier C | 2 |
| M20 | Organization system | Major | 2 | Tier C | 2 |

Cards = number of cards carrying the label (a card can serve several modules). Point totals are in [overview.md](overview.md#module-plan).

## Counts (2026-11-04)

97 cards: To Do 23 (S1), Backlog 74 (S2 28, S3 27, S4 12, sprint per due date 2, tier C 5).

| Owner | S1 | S2 | S3 | S4 | Backlog, per due date | Tier C | Total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| byul-byul | 8 | 6 | 7 | 3 | 0 | 0 | 24 |
| Khalil | 4 | 4 | 5 | 1 | 0 | 2 | 16 |
| Nader | 3 | 6 | 5 | 2 | 1 | 1 | 18 |
| Zayid | 6 | 7 | 3 | 5 | 0 | 1 | 22 |
| Ahmad | 2 | 5 | 7 | 1 | 1 | 1 | 17 |
| **Total** | **23** | **28** | **27** | **12** | **2** | **5** | **97** |

By prefix: FE 34, BE 28, INF 16, DOC 8, TC 5, QA 4, PM 2.
