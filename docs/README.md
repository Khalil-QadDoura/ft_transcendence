# Project docs

Draft for discussion. Read `plan/overview.md` first, then the doc for your track, and send comments before our next call.

| Document | For whom | Kind |
| --- | --- | --- |
| [plan/overview.md](plan/overview.md) | Everyone | Living: roles, module plan, risks, ways of working, decisions log |
| [api/api-contract.md](api/api-contract.md) | Frontend + backend | Living: every endpoint, WebSocket events, planned changes |
| [api/wozu-reference-openapi.json](api/wozu-reference-openapi.json) | Frontend + backend | Snapshot of the WOZU reference API (OpenAPI 3.1), do not edit |
| [game/turing-duel-rules.md](game/turing-duel-rules.md) | Everyone | Living: Turing Duel rules, scoring, outcomes, "No bot leak" |
| [infra/infrastructure.md](infra/infrastructure.md) | Infrastructure | Living: services, HTTPS routing, storage, email, infra modules |
| [reference/wozu-backend.md](reference/wozu-backend.md) | Backend | Snapshot of the WOZU backend as of 2026-10-27, do not edit |
| [ft_transcendence.subject.txt](ft_transcendence.subject.txt) | Everyone | Project subject, v21.1 |

## Rules

- Living docs change through PRs like code; a PR that changes the API also updates `api/api-contract.md`.
- Snapshots stay as they are; write corrections into the living docs.
- Decisions go into the decisions log at the end of `plan/overview.md`.

## Reference code

WOZU backend used as a reference: https://github.com/byul-byul/ft_transcendence (branch `main`).

## AI usage

These documents were drafted with AI assistance (Claude) from the WOZU backend code and the subject, then reviewed by the team. To be listed in the root README "Resources" section before submission.
