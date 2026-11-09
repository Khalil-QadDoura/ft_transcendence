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

Routing, auth guards and the responsive shell follow in FE-02; API auth belongs to FE-20/FE-04. AI assistance (Codex) was used for this scaffold, documentation and checks. Zayid must review and be able to explain the changes before defense. Human cross-pair review and green CI are required before merge, per PM-00.
