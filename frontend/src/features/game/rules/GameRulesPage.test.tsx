import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { routes } from "../../../app/router";
import { SessionContext } from "../../../app/session";
import i18n, { languages } from "../../../i18n";
import { EXAMPLE_A, EXAMPLE_B } from "./examples";
import { GAME_RULES_PATH } from "./paths";
import { scoreGame } from "./scoring";

let root: Root;
let container: HTMLDivElement;
let consoleSpies: ReturnType<typeof vi.spyOn>[];
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  consoleSpies = (["error", "warn", "log"] as const).map((method) =>
    vi.spyOn(console, method),
  );
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  await i18n.changeLanguage("en");
  for (const spy of consoleSpies) expect(spy).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

async function renderRules() {
  const router = createMemoryRouter(routes, {
    initialEntries: [GAME_RULES_PATH],
  });
  await act(() =>
    root.render(
      <SessionContext value="anonymous">
        <RouterProvider router={router} />
      </SessionContext>,
    ),
  );
  return router;
}

const page = () => container.querySelector("main article")!;
const signed = (language: string, value: number) =>
  new Intl.NumberFormat(language, { signDisplay: "exceptZero" }).format(value);
const t = (key: string, options?: Record<string, unknown>) =>
  i18n.t(key, { ns: "gameRules", ...options });

test("/game/rules renders for a logged-out visitor with one h1 and every section", async () => {
  const router = await renderRules();
  expect(router.state.location.pathname).toBe("/game/rules");
  expect(container.querySelectorAll("h1")).toHaveLength(1);
  expect(container.querySelector("h1")!.textContent).toBe("Game rules");
  const headings = Array.from(page().querySelectorAll("h2")).map(
    (heading) => heading.textContent,
  );
  expect(headings).toEqual([
    "The idea",
    "Rooms and participants",
    "Waiting room",
    "Discussion phase: 120 seconds",
    "Voting phase: 45 seconds",
    "Scoring",
    "Win, draw and loss",
    "If a player disconnects",
    "Results",
    "Worked examples",
  ]);
  // Every section is reachable from the contents list.
  const anchors = Array.from(page().querySelectorAll("nav a")).map((a) =>
    a.getAttribute("href"),
  );
  for (const section of Array.from(
    page().querySelectorAll("section[aria-labelledby]"),
  ))
    expect(anchors).toContain(`#${section.getAttribute("aria-labelledby")}`);
  const text = page().textContent!;
  for (const phrase of [
    "A room holds up to 5 participants, and at least 1 of them is a human.",
    "from “Player 1” to “Player 5”",
    "A room has no bots, or 1 to 4 of them.",
    "One room timer of 3 minutes starts when the room is created.",
    "while the room has 2 to 4 participants",
    "The room reaches 5 participants.",
    "The room timer runs out and the room has 2 or more participants.",
    "with only 1 participant in the room, the room closes",
    "every other participant is already marked “human”",
    "Correct guess (a bot marked bot, a human marked human): +1 point",
    "Wrong guess (a bot marked human, a human marked bot): -1 point",
    "With 2 or more humans: the human with the highest score wins, even if that score is 0 or negative.",
    "a score above 0 is a win, exactly 0 is a draw, below 0 is a loss",
    "keeps the marks they had at that moment",
    "each bot's deception rate",
  ])
    expect(text).toContain(phrase);
  expect(
    container.querySelector('footer a[href="/game/rules"]'),
  ).not.toBeNull();
});

test("the worked examples are real tables with a caption and scoped header cells", async () => {
  await renderRules();
  const tables = page().querySelectorAll("table");
  expect(tables).toHaveLength(2);
  for (const table of Array.from(tables)) {
    expect(table.querySelector("caption")?.textContent).toBeTruthy();
    const headers = Array.from(table.querySelectorAll("th"));
    expect(headers.length).toBeGreaterThan(0);
    for (const header of headers)
      expect(["col", "row"]).toContain(header.getAttribute("scope"));
    expect(table.querySelectorAll('thead th[scope="col"]').length).toBe(
      table.querySelector("thead tr")!.children.length,
    );
    expect(table.querySelectorAll('tbody th[scope="row"]').length).toBe(
      table.querySelectorAll("tbody tr").length,
    );
  }
  expect(tables[0].querySelector("caption")!.textContent).toBe(
    "Example A: marks, scores and outcomes",
  );
});

test("example A renders the computed marks, scores, outcomes and deception rates", async () => {
  await renderRules();
  const result = scoreGame(EXAMPLE_A.participants, EXAMPLE_A.marks);
  const table = page().querySelectorAll("table")[0];
  for (const human of result.humans) {
    const row = table.querySelector(`tr[data-voter="${human.label}"]`)!;
    const cells = Array.from(row.children).map((cell) => cell.textContent);
    expect(cells[0]).toBe(`Player ${human.label}`);
    const scoreCell = row.querySelector("[data-score]")!;
    expect(scoreCell.getAttribute("data-score")).toBe(String(human.score));
    expect(scoreCell.querySelector("strong")!.textContent).toBe(
      signed("en", human.score),
    );
    expect(row.querySelector("[data-outcome]")!.textContent).toBe(
      t(`examples.outcomes.${human.outcome}`),
    );
    for (const guess of human.guesses) {
      const index = EXAMPLE_A.participants.findIndex(
        ({ label }) => label === guess.target,
      );
      expect(cells[index + 1]).toBe(
        `${guess.mark} ${guess.correct ? "✓" : "✗"} (${guess.correct ? "correct" : "wrong"})`,
      );
    }
  }
  expect(
    Array.from(table.querySelectorAll("tbody tr")).map((row) => [
      row.querySelector("strong")!.textContent,
      row.querySelector("[data-outcome]")!.textContent,
    ]),
  ).toEqual([
    ["+4", "Win"],
    ["+2", "Loss"],
    ["+2", "Loss"],
  ]);
  expect(table.querySelector('tr[data-voter="1"] td')!.textContent).toBe(
    "(self)",
  );
  expect(
    Array.from(page().querySelectorAll("li[data-bot]")).map(
      (li) => li.textContent,
    ),
  ).toEqual([
    "Player 3: marked “human” by 1 of 3 humans, a deception rate of 33%.",
    "Player 5: marked “human” by 0 of 3 humans, a deception rate of 0%.",
  ]);
  expect(page().textContent).toContain(
    "If Player 1 had also scored +2, all 3 humans would share the top score and all of them would draw.",
  );
});

test("example B renders a win at +2, a draw at 0 and a loss at -2", async () => {
  await renderRules();
  const rows = Array.from(
    page().querySelectorAll("table")[1].querySelectorAll("tbody tr"),
  );
  expect(rows).toHaveLength(EXAMPLE_B.scenarios.length);
  expect(
    rows.map((row) => [
      row.querySelector("th")!.textContent,
      row.querySelector("[data-score]")!.textContent,
      row.querySelector("[data-outcome]")!.textContent,
    ]),
  ).toEqual([
    ["Player 1 bot ✓ (correct), Player 4 bot ✓ (correct)", "+1 +1 = +2", "Win"],
    ["Player 1 bot ✓ (correct), Player 4 human ✗ (wrong)", "+1 -1 = 0", "Draw"],
    [
      "Player 1 human ✗ (wrong), Player 4 human ✗ (wrong)",
      "-1 -1 = -2",
      "Loss",
    ],
  ]);
});

test("Arabic switches the page to RTL and formats signed numbers with Intl for ar", async () => {
  await renderRules();
  await act(() => i18n.changeLanguage("ar"));
  expect(document.documentElement.dir).toBe("rtl");
  expect(document.documentElement.lang).toBe("ar");
  expect(container.querySelector("h1")!.textContent).toBe("قواعد اللعبة");
  const scores = Array.from(
    page().querySelectorAll("table")[0].querySelectorAll("tbody strong"),
  ).map((strong) => strong.textContent);
  expect(scores).toEqual([4, 2, 2].map((score) => signed("ar", score)));
  expect(page().textContent).toContain(
    t("scoring.wrong", { points: signed("ar", -1) }),
  );
  expect(page().textContent).toContain(new Intl.NumberFormat("ar").format(120));
});

test.each(languages)(
  "%s: every key resolves and no implementer terms appear",
  async (language) => {
    await renderRules();
    await act(() => i18n.changeLanguage(language));
    const walker = document.createTreeWalker(page(), NodeFilter.SHOW_TEXT);
    const rawKeys: string[] = [];
    while (walker.nextNode()) {
      const value = walker.currentNode.textContent!.trim();
      if (/^[a-z]+(\.[a-zA-Z_]+)+$/.test(value)) rawKeys.push(value);
    }
    expect(rawKeys).toEqual([]);
    const text = page().textContent!;
    expect(text).not.toMatch(
      /\block(s|ed)?\b|winner_participant_ids|is_draw|is_bot|user_id|participant_id|websocket|\bapi\b|\bserver\b|no bot leak/i,
    );
  },
);
