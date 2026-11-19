// The two worked examples of docs/game/turing-duel-rules.md section 6, as data.
// Only the marks are written here; scores, outcomes and deception rates come
// from scoring.ts. `npm run rules:check` compares both with the rules file.
import type { Marks, Participant } from "./scoring";

/** Worked example A: 3 humans and 2 bots in a room of 5. */
export const EXAMPLE_A: {
  participants: Participant[];
  marks: Marks;
  /** "If Player 1 had also scored +2, all three humans would … draw." */
  tie: { label: number; score: number };
} = {
  participants: [
    { label: 1, kind: "human" },
    { label: 2, kind: "human" },
    { label: 3, kind: "bot" },
    { label: 4, kind: "human" },
    { label: 5, kind: "bot" },
  ],
  marks: {
    1: { 2: "human", 3: "bot", 4: "human", 5: "bot" },
    2: { 1: "human", 3: "human", 4: "human", 5: "bot" },
    4: { 1: "bot", 2: "human", 3: "bot", 5: "bot" },
  },
  tie: { label: 1, score: 2 },
};

/** Worked example B: 1 human and 2 bots in a room of 3, three sets of guesses. */
export const EXAMPLE_B: {
  participants: Participant[];
  scenarios: Marks[];
} = {
  participants: [
    { label: 1, kind: "bot" },
    { label: 2, kind: "human" },
    { label: 4, kind: "bot" },
  ],
  scenarios: [
    { 2: { 1: "bot", 4: "bot" } },
    { 2: { 1: "bot", 4: "human" } },
    { 2: { 1: "human", 4: "human" } },
  ],
};
