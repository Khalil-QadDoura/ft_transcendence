# WOZU — ft_transcendence

WOZU connects candidates and employers through profiles, video introductions, job applications, conversations, and Turing Duel.

This branch adds a working web prototype connected to a separate, pinned copy of the existing WOZU backend. The frontend does not replace the team's planned backend.

## Start here

- [Run the frontend and reference backend](frontend/README.md)
- [Project plan](docs/plan/overview.md)
- [API contract](docs/api/api-contract.md)
- [Reference backend](docs/reference/wozu-backend.md)
- [Trello board](https://trello.com/b/E3788fBx/fttranscendence)

## Web development

```sh
cd frontend
npm ci
npm run dev
```

The UI runs at http://127.0.0.1:5173 and expects the reference API at port 8000. Follow the frontend README for the isolated database, storage, demo accounts, and integration checks.

## Scope

The branch implements the candidate and employer web journeys and packages a small reference-backend compatibility patch. Real email/AI provider configuration, complete localization, production hardening, and remaining subject/board requirements are tracked explicitly in the frontend README. This is a reviewable prototype branch, not a claim that all project requirements are complete.

Implementation is AI-assisted. Original reference backend authorship is retained; commit dates and development history reflect the actual work.
