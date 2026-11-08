# WOZU frontend

FE-01 introduces the React + TypeScript (strict) foundation. Node 24 and npm are required.

```sh
npm ci
cp .env.example .env
npm run dev
```

Open http://127.0.0.1:5174. Port 5174 allows the separate visual prototype on 5173 to remain available. The Vite `/api` proxy targets the local reference backend on port 8000 and strips `/api`. Set `API_PROXY_STRIP_PREFIX=false` when using the team's prefixed backend. This development server is loopback-only; production HTTPS belongs to INF-03.

## Checks

`npm run lint`, `npm run format:check`, `npm run typecheck`, `npm test`, and `npm run build` run in the frontend CI job. `npm run format` formats maintained source and configuration; generated schema and lockfile are excluded.

## API types

`npm run gen:api` reads `http://127.0.0.1:5174/api/openapi.json` and commits its output to `src/api/schema.d.ts`. The reference backend protects its schema at `/_internal/openapi.json`, so use the checked-in reference export until BE-01 exposes `/api/openapi.json`: `npm run gen:api -- ../docs/api/wozu-reference-openapi.json`. Set `OPENAPI_URL` to the team backend URL when BE-01 lands. An explicit URL or checked-in spec can also be passed: `npm run gen:api -- ../docs/api/wozu-reference-openapi.json`. Generation is explicit, never a network dependency of a normal build. The initial types describe the current reference, not the planned contract changes.

## Structure

- `src/app`: router, providers, global styles.
- `src/features/<domain>`: domain screens and tests; `home` is the initial entry.
- `src/components`: shared UI (FE-21).
- `src/api`: generated schema; API client follows in FE-20.
- `src/i18n`: reserved for FE-06; i18next and react-i18next are installed.

## Container

`docker build -t wozu-frontend .` builds static assets and an nginx preview image. `docker run --rm -p 127.0.0.1:8080:80 wozu-frontend` serves it. INF-03 can use the named `build` stage and copy `/app/dist` to the shared HTTPS proxy. Never embed secrets in Vite environment variables.

## Scope and review

FE-02 adds the responsive shell, all planned route slots, legal navigation, 404, route focus management and the auth guard. The home artwork is original SVG; typography is bundled locally. Reduced-motion preferences stop the animation.

`SessionContext` is the integration boundary: FE-04/FE-20 must provide `loading`, `anonymous` or `authenticated` from a verified backend session. Protected routes preserve the path, query and hash in `/login?next=`. Once the provider changes to `authenticated`, `GuestOnly` restores a safe internal destination. No fake login or persistent browser flag is used. Route tests inject session states; real login is still FE-04 work.

Other route slots explicitly display a coming-soon state. Privacy/Terms content awaits DOC-01/DOC-02 and FE-13; the empty slots do not satisfy the subject's final legal-content requirement. Language and unread header slots await FE-06/FE-22. The nginx preview config falls back to `index.html` for client routes while missing compiled assets correctly return 404. INF-03 must preserve this behavior in the production HTTPS proxy.

Validation: lint, formatting, strict TypeScript, 31 route/redirect tests, Vite production build, Docker build, browser checks at 360 px and desktop, and reloads of protected/public routes. Reproduce with the commands above; production deep-link checks use the Docker preview on port 8080.

AI assistance (Codex) was used for the scaffold, shell, artwork, documentation and checks. Zayid must review and be able to explain the changes before defense. Human cross-pair review and green CI are required before merge, per PM-00. FE-02 depends on FE-01 and should be reviewed against that branch, then retargeted to main after FE-01 merges.

FE-03 adds [shared form validation](docs/form-validation.md): per-domain Zod schemas, React Hook Form resolver setup, and safe mapping of backend 422 errors. The guide records pending backend contracts, translation keys and consumer responsibilities.
