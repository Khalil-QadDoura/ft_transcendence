// Drift check for the game rules page (FE-34), run by `npm run rules:check`.
// Every number the page states (src/features/game/rules/constants.ts) and the
// scores, outcomes and deception rates computed for the worked examples must
// appear in docs/game/turing-duel-rules.md exactly as stated there.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import * as rules from "../src/features/game/rules/constants";
import { EXAMPLE_A, EXAMPLE_B } from "../src/features/game/rules/examples";
import {
  decideOutcomes,
  scoreGame,
  type Kind,
  type Outcome,
} from "../src/features/game/rules/scoring";

const source = fileURLToPath(
  new URL("../../docs/game/turing-duel-rules.md", import.meta.url),
);
const doc = readFileSync(source, "utf8").replace(/\r\n/g, "\n");

/** Signed points as the rules file writes them: +1, −1 (U+2212), 0. */
const signed = (value: number) =>
  value > 0 ? `+${value}` : value < 0 ? `−${-value}` : "0";
const parseSigned = (text: string) => Number(text.replace("−", "-"));
const player = (label: number) => `Player ${label}`;
const englishList = (items: string[]) =>
  items.length < 2
    ? items.join("")
    : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
const outcomeWord: Record<Outcome, string> = {
  win: "Win",
  draw: "Draw",
  loss: "Loss",
};

/** The text of a "### heading" section, up to the next heading of level 2 or 3. */
function section(heading: string): string {
  const start = doc.indexOf(`\n### ${heading}`);
  expect(start, `section "${heading}" in ${source}`).toBeGreaterThan(-1);
  const rest = doc.slice(start + 1);
  const end = rest.slice(4).search(/\n#{2,3} /);
  return end === -1 ? rest : rest.slice(0, end + 4);
}
const tableRows = (text: string) =>
  text
    .split("\n")
    .filter((line) => line.startsWith("| Player "))
    .map((line) =>
      line
        .slice(1, -1)
        .split("|")
        .map((cell) => cell.trim()),
    );
/** "+1 −1 +1 +1 = **+2**" → { points: [1, -1, 1, 1], total: 2 } */
function scoreCell(cell: string) {
  const match = cell.match(/^(.*) = \*\*([+−]?\d+)\*\*$/);
  expect(match, `score cell "${cell}"`).not.toBeNull();
  return {
    points: match![1].split(" ").map(parseSigned),
    total: parseSigned(match![2]),
  };
}

describe("numbers on the rules page", () => {
  const C = rules;
  test.each([
    [
      "MAX_PARTICIPANTS, MIN_HUMANS",
      `A room holds up to ${C.MAX_PARTICIPANTS} participants, and at least ${C.MIN_HUMANS} of them is a human.`,
    ],
    [
      "MAX_PARTICIPANTS, MIN_HUMANS (summary)",
      `| Participants per room | up to ${C.MAX_PARTICIPANTS}, at least ${C.MIN_HUMANS} human |`,
    ],
    [
      "FIRST_LABEL, LAST_LABEL",
      `a random free number from ${C.FIRST_LABEL} to ${C.LAST_LABEL}`,
    ],
    [
      "FIRST_LABEL, LAST_LABEL (labels)",
      `"Player ${C.FIRST_LABEL}" … "Player ${C.LAST_LABEL}"`,
    ],
    [
      "MIN_BOTS_WHEN_ANY, MAX_BOTS",
      `| Bots per room | none, or ${C.MIN_BOTS_WHEN_ANY} to ${C.MAX_BOTS}, decided secretly by the server |`,
    ],
    [
      "ROOM_TIMER_MINUTES",
      `A single ${C.ROOM_TIMER_MINUTES}-minute timer starts when the room is created. It never restarts`,
    ],
    [
      "ROOM_TIMER_MINUTES (summary)",
      `| Room timer | ${C.ROOM_TIMER_MINUTES} minutes from room creation, never restarts |`,
    ],
    [
      "MAX_PARTICIPANTS (full room starts)",
      `1. The ${C.MAX_PARTICIPANTS}th participant joins.`,
    ],
    [
      "MIN_PARTICIPANTS_TO_START, START_NOW_MAX_PARTICIPANTS",
      `2. A human presses "Start now" (visible while the room has ${C.MIN_PARTICIPANTS_TO_START} to ${C.START_NOW_MAX_PARTICIPANTS} participants).`,
    ],
    [
      "MIN_PARTICIPANTS_TO_START, START_NOW_MAX_PARTICIPANTS (waiting room)",
      `while the room has ${C.MIN_PARTICIPANTS_TO_START} to ${C.START_NOW_MAX_PARTICIPANTS} participants, a "Start now" button`,
    ],
    [
      "MIN_PARTICIPANTS_TO_START (timer)",
      `3. The room timer runs out and the room has ${C.MIN_PARTICIPANTS_TO_START} or more participants.`,
    ],
    [
      "ROOM_CLOSES_WITH_PARTICIPANTS",
      `If the room timer runs out with only ${C.ROOM_CLOSES_WITH_PARTICIPANTS} participant, the room closes.`,
    ],
    [
      "DISCUSSION_SECONDS",
      `## 4. Discussion phase (${C.DISCUSSION_SECONDS} seconds)`,
    ],
    [
      "DISCUSSION_SECONDS (summary)",
      `| Discussion phase | ${C.DISCUSSION_SECONDS} seconds |`,
    ],
    ["VOTING_SECONDS", `## 5. Voting phase (${C.VOTING_SECONDS} seconds)`],
    [
      "VOTING_SECONDS (summary)",
      `| Voting phase | ${C.VOTING_SECONDS} seconds |`,
    ],
    [
      "VOTING_SECONDS (marks)",
      `as often as they like until the ${C.VOTING_SECONDS} seconds end.`,
    ],
    [
      "DEFAULT_MARK",
      `When voting starts, every other participant is already marked "${C.DEFAULT_MARK}".`,
    ],
    [
      "DEFAULT_MARK (no missing guess)",
      `There is no "no guess": a mark left at "${C.DEFAULT_MARK}" counts like any other.`,
    ],
    [
      "POINTS_CORRECT",
      `| Correct (a bot marked bot, a human marked human) | ${signed(C.POINTS_CORRECT)} |`,
    ],
    [
      "POINTS_WRONG",
      `| Wrong (a bot marked human, a human marked bot) | ${signed(C.POINTS_WRONG)} |`,
    ],
    [
      "POINTS_CORRECT, POINTS_WRONG, DEFAULT_MARK (summary)",
      `| Points per guess | ${signed(C.POINTS_CORRECT)} correct, ${signed(C.POINTS_WRONG)} wrong; every mark starts at "${C.DEFAULT_MARK}" and counts |`,
    ],
    [
      "RELATIVE_OUTCOME_MIN_HUMANS",
      `With ${C.RELATIVE_OUTCOME_MIN_HUMANS} or more humans: the human with the highest score wins, even if that score is 0 or negative`,
    ],
    [
      "RELATIVE_OUTCOME_MIN_HUMANS, SINGLE_HUMAN_THRESHOLD",
      `With exactly ${C.RELATIVE_OUTCOME_MIN_HUMANS - 1} human in the room (that human plus bots): a score above ${C.SINGLE_HUMAN_THRESHOLD} is a win, exactly ${C.SINGLE_HUMAN_THRESHOLD} is a draw, below ${C.SINGLE_HUMAN_THRESHOLD} is a loss.`,
    ],
  ])("%s", (_name, phrase) => {
    expect(doc).toContain(phrase);
  });
});

describe("worked example A", () => {
  const text = section("Worked example A");
  const result = scoreGame(EXAMPLE_A.participants, EXAMPLE_A.marks);
  const header = text
    .split("\n")
    .find((line) => line.startsWith("| Marked by |"))!;
  const columns = header
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim())
    .slice(1, -1)
    .map((cell) => Number(cell.replace("Player ", "")));
  const rows = tableRows(text);

  test("participants and who is a bot", () => {
    const labels = (kind: Kind) =>
      EXAMPLE_A.participants
        .filter((participant) => participant.kind === kind)
        .map(({ label }) => player(label));
    expect(text).toContain(
      `Room of ${EXAMPLE_A.participants.length}. Humans are ${englishList(labels("human"))}. Bots are ${englishList(labels("bot"))}. Each human marks the ${EXAMPLE_A.participants.length - 1} other participants.`,
    );
    expect(columns).toEqual(EXAMPLE_A.participants.map(({ label }) => label));
  });

  test("the marks table matches EXAMPLE_A.marks, with ✓/✗ as computed", () => {
    const marks = Object.fromEntries(
      rows.map(([voter, ...cells]) => [
        Number(voter.replace("Player ", "")),
        Object.fromEntries(
          cells
            .slice(0, columns.length)
            .map((cell, index) => [columns[index], cell] as const)
            .filter(([, cell]) => cell !== "(self)")
            .map(([target, cell]) => [target, cell.split(" ")[0]]),
        ),
      ]),
    );
    expect(marks).toEqual(EXAMPLE_A.marks);
    for (const human of result.humans) {
      const row = rows.find(([voter]) => voter === player(human.label))!;
      for (const guess of human.guesses)
        expect(row[columns.indexOf(guess.target) + 1]).toBe(
          `${guess.mark} ${guess.correct ? "✓" : "✗"}`,
        );
    }
  });

  test("every score in the file equals the computed score", () => {
    expect(
      rows.map(([voter, ...cells]) => [voter, scoreCell(cells.at(-1)!)]),
    ).toEqual(
      result.humans.map((human) => [
        player(human.label),
        {
          points: human.guesses.map(({ points }) => points),
          total: human.score,
        },
      ]),
    );
  });

  test("the outcome sentence names the computed winner and losers", () => {
    const [winner] = result.humans.filter(({ outcome }) => outcome === "win");
    const losers = result.humans.filter(({ outcome }) => outcome === "loss");
    expect(result.humans.filter(({ outcome }) => outcome === "draw")).toEqual(
      [],
    );
    expect(new Set(losers.map(({ score }) => score)).size).toBe(1);
    expect(text).toContain(
      `Outcome: ${player(winner.label)} has the highest score (${signed(winner.score)}) and wins. ${englishList(losers.map(({ label }) => player(label)))} share ${signed(losers[0].score)}, but that is not the top score, so both lose.`,
    );
  });

  test("deception rates match the computed rates", () => {
    for (const bot of result.bots)
      expect(text).toMatch(
        new RegExp(
          `^- ${player(bot.label)}: .* ${bot.fooled} of ${bot.humans} → ${Math.round(bot.rate * 100)}%\\.$`,
          "m",
        ),
      );
  });

  test("the tie variant is a draw for every human", () => {
    expect(
      decideOutcomes(
        result.humans.map(({ label, score }) =>
          label === EXAMPLE_A.tie.label ? EXAMPLE_A.tie.score : score,
        ),
      ),
    ).toEqual(result.humans.map(() => "draw"));
    expect(text).toContain(
      `If ${player(EXAMPLE_A.tie.label)} had also scored ${signed(EXAMPLE_A.tie.score)}, all three humans would share the top score and all three would draw.`,
    );
  });
});

describe("worked example B", () => {
  const text = section("Worked example B");
  const rows = tableRows(text);
  const human = EXAMPLE_B.participants.find(({ kind }) => kind === "human")!;

  test("participants and who is a bot", () => {
    expect(text).toContain(
      `Room of ${EXAMPLE_B.participants.length}. The human is ${player(human.label)}. Bots are ${englishList(
        EXAMPLE_B.participants
          .filter(({ kind }) => kind === "bot")
          .map(({ label }) => player(label)),
      )}.`,
    );
  });

  test("each row's guesses, score and outcome match the computed ones", () => {
    expect(rows).toHaveLength(EXAMPLE_B.scenarios.length);
    rows.forEach(([guesses, score, outcome], index) => {
      const [result] = scoreGame(
        EXAMPLE_B.participants,
        EXAMPLE_B.scenarios[index],
      ).humans;
      expect(guesses).toBe(
        result.guesses
          .map(
            (guess) =>
              `${player(guess.target)} ${guess.mark} ${guess.correct ? "✓" : "✗"}`,
          )
          .join(", "),
      );
      expect(scoreCell(score)).toEqual({
        points: result.guesses.map(({ points }) => points),
        total: result.score,
      });
      expect(outcome.split(" ")[0]).toBe(outcomeWord[result.outcome]);
    });
  });
});
