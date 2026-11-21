import { describe, expect, test } from "vitest";
import { EXAMPLE_A, EXAMPLE_B } from "./examples";
import {
  decideOutcomes,
  guessPoints,
  markOf,
  scoreGame,
  type Participant,
} from "./scoring";

const room: Participant[] = [
  { label: 1, kind: "human" },
  { label: 2, kind: "human" },
  { label: 3, kind: "bot" },
];

describe("points per guess", () => {
  test("a correct guess earns +1, a wrong one costs 1", () => {
    expect(guessPoints("bot", "bot")).toBe(1);
    expect(guessPoints("human", "human")).toBe(1);
    expect(guessPoints("human", "bot")).toBe(-1);
    expect(guessPoints("bot", "human")).toBe(-1);
  });

  test('a missing mark is the preset "human" and counts +1 or -1, never 0', () => {
    expect(markOf({}, 1, 3)).toBe("human");
    const { humans } = scoreGame(room, {});
    // Player 1 left both marks at "human": Player 2 is human (+1), Player 3 a bot (-1).
    expect(humans[0].guesses.map(({ points }) => points)).toEqual([1, -1]);
    expect(humans[0].score).toBe(0);
    expect(
      humans.flatMap(({ guesses }) => guesses).some((g) => g.points === 0),
    ).toBe(false);
  });

  test("a human never marks themselves; the score sums one mark per other participant", () => {
    const { humans } = scoreGame(room, {
      1: { 1: "bot", 2: "human", 3: "bot" },
      2: { 1: "bot", 3: "human" },
    });
    expect(humans.map(({ label }) => label)).toEqual([1, 2]);
    expect(humans[0].guesses.map(({ target }) => target)).toEqual([2, 3]);
    expect(humans[0].score).toBe(2);
    expect(humans[1].score).toBe(-2);
  });
});

describe("outcomes", () => {
  test("with 2 or more humans the single top score wins and the rest lose", () => {
    expect(decideOutcomes([4, 2, 2])).toEqual(["win", "loss", "loss"]);
  });

  test("the top score wins even when it is 0 or below", () => {
    expect(decideOutcomes([0, -2])).toEqual(["win", "loss"]);
    expect(decideOutcomes([-4, -2, -3])).toEqual(["loss", "win", "loss"]);
  });

  test("a shared top score is a draw for those players, everyone else loses", () => {
    expect(decideOutcomes([2, 2, 2])).toEqual(["draw", "draw", "draw"]);
    expect(decideOutcomes([3, 1, 3])).toEqual(["draw", "loss", "draw"]);
    expect(decideOutcomes([-1, -1])).toEqual(["draw", "draw"]);
  });

  test("a single human wins above 0, draws at 0 and loses below 0", () => {
    expect(decideOutcomes([2])).toEqual(["win"]);
    expect(decideOutcomes([0])).toEqual(["draw"]);
    expect(decideOutcomes([-2])).toEqual(["loss"]);
  });

  test("bots get no outcome", () => {
    const { humans, bots } = scoreGame(room, {});
    expect(humans).toHaveLength(2);
    expect(bots[0]).not.toHaveProperty("outcome");
  });
});

describe("worked examples of docs/game/turing-duel-rules.md", () => {
  test("example A: +4 wins, the two +2 lose, deception 1 of 3 and 0 of 3", () => {
    const { humans, bots } = scoreGame(EXAMPLE_A.participants, EXAMPLE_A.marks);
    expect(
      humans.map(({ label, guesses, score, outcome }) => [
        label,
        guesses.map(({ points }) => points),
        score,
        outcome,
      ]),
    ).toEqual([
      [1, [1, 1, 1, 1], 4, "win"],
      [2, [1, -1, 1, 1], 2, "loss"],
      [4, [-1, 1, 1, 1], 2, "loss"],
    ]);
    expect(bots).toEqual([
      { label: 3, fooled: 1, humans: 3, rate: 1 / 3 },
      { label: 5, fooled: 0, humans: 3, rate: 0 },
    ]);
    expect(decideOutcomes([EXAMPLE_A.tie.score, 2, 2])).toEqual([
      "draw",
      "draw",
      "draw",
    ]);
  });

  test("example B: +2 wins, 0 draws, -2 loses", () => {
    const rows = EXAMPLE_B.scenarios.map((marks) => {
      const [human] = scoreGame(EXAMPLE_B.participants, marks).humans;
      return [human.score, human.outcome];
    });
    expect(rows).toEqual([
      [2, "win"],
      [0, "draw"],
      [-2, "loss"],
    ]);
  });
});
