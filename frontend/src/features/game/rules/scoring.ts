// Pure scoring of a Turing Duel game as docs/game/turing-duel-rules.md
// sections 5 to 7 define it. The rules page renders its worked examples from
// these functions; nothing here talks to the server.
import {
  DEFAULT_MARK,
  POINTS_CORRECT,
  POINTS_WRONG,
  RELATIVE_OUTCOME_MIN_HUMANS,
  SINGLE_HUMAN_THRESHOLD,
} from "./constants";

export type Kind = "bot" | "human";
export type Outcome = "win" | "draw" | "loss";

export interface Participant {
  label: number;
  kind: Kind;
}

/** marks[voter][target]. A missing entry is the preset "human" mark. */
export type Marks = Readonly<
  Partial<Record<number, Readonly<Partial<Record<number, Kind>>>>>
>;

export interface Guess {
  target: number;
  mark: Kind;
  correct: boolean;
  points: number;
}

export interface HumanResult {
  label: number;
  guesses: Guess[];
  score: number;
  outcome: Outcome;
}

export interface BotResult {
  label: number;
  /** Humans whose mark on this bot was "human" when voting ended. */
  fooled: number;
  /** Humans in the game, disconnected players included. */
  humans: number;
  /** fooled ÷ humans, between 0 and 1. */
  rate: number;
}

export interface GameResult {
  humans: HumanResult[];
  bots: BotResult[];
}

export function markOf(marks: Marks, voter: number, target: number): Kind {
  return marks[voter]?.[target] ?? DEFAULT_MARK;
}

export function guessPoints(mark: Kind, actual: Kind): number {
  return mark === actual ? POINTS_CORRECT : POINTS_WRONG;
}

/** Outcomes for the humans' scores, in the same order. */
export function decideOutcomes(scores: readonly number[]): Outcome[] {
  if (scores.length === 0) return [];
  if (scores.length < RELATIVE_OUTCOME_MIN_HUMANS) {
    return scores.map((score) =>
      score > SINGLE_HUMAN_THRESHOLD
        ? "win"
        : score === SINGLE_HUMAN_THRESHOLD
          ? "draw"
          : "loss",
    );
  }
  const top = Math.max(...scores);
  const shared = scores.filter((score) => score === top).length > 1;
  return scores.map((score) =>
    score < top ? "loss" : shared ? "draw" : "win",
  );
}

/** Scores, outcomes and bot deception rates for one finished game. */
export function scoreGame(
  participants: readonly Participant[],
  marks: Marks,
): GameResult {
  const ordered = [...participants].sort((a, b) => a.label - b.label);
  const humans = ordered.filter(({ kind }) => kind === "human");
  const scored = humans.map(({ label }) => {
    const guesses = ordered
      .filter((target) => target.label !== label)
      .map((target): Guess => {
        const mark = markOf(marks, label, target.label);
        const points = guessPoints(mark, target.kind);
        return {
          target: target.label,
          mark,
          correct: mark === target.kind,
          points,
        };
      });
    const score = guesses.reduce((sum, { points }) => sum + points, 0);
    return { label, guesses, score };
  });
  const outcomes = decideOutcomes(scored.map(({ score }) => score));
  const bots = ordered
    .filter(({ kind }) => kind === "bot")
    .map(({ label }): BotResult => {
      const fooled = humans.filter(
        (human) => markOf(marks, human.label, label) === "human",
      ).length;
      return {
        label,
        fooled,
        humans: humans.length,
        rate: humans.length ? fooled / humans.length : 0,
      };
    });
  return {
    humans: scored.map((human, index) => ({
      ...human,
      outcome: outcomes[index],
    })),
    bots,
  };
}
