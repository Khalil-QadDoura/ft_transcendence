# FE-34: game rules page

`/game/rules` is a public route inside the common layout (no login). It shows sections 1 to 8 of [docs/game/turing-duel-rules.md](../../docs/game/turing-duel-rules.md) for players; section 9 (implementer notes) is left out on purpose. The footer and the home page link to it through `GAME_RULES_PATH` (`src/features/game/rules/paths.ts`); new links use that constant.

- `src/features/game/rules/constants.ts`: every number the page states (room size, bots, timer, phase lengths, points, outcome thresholds). The texts interpolate these values; no number is written in the locale files.
- `src/features/game/rules/scoring.ts`: pure scoring (points per guess, score, win/draw/loss, deception rate). The worked examples on the page are computed with it, not typed in.
- `src/features/game/rules/examples.ts`: the marks of worked examples A and B, exactly as in the rules file.
- Texts: namespace `gameRules` in `src/i18n/<language>/gameRules.json` (EN, AR, AZ, TR, RU). Numbers go through `Intl.NumberFormat` for the active language; signed points use `signDisplay: "exceptZero"`.

`npm run rules:check` (`scripts/game-rules.drift.ts`, run in the CI `frontend` job) fails when a constant, a mark, a score, an outcome or a deception rate disagrees with the rules file. It is not part of `npm test` because `make test` builds `frontend/` alone and has no `docs/`.

Changing a rule: change the rules file first (PO decision), then `constants.ts` or `examples.ts`, then the texts if the wording changed. Run `npm test` and `npm run rules:check`.
