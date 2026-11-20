// Every number the game rules page (/game/rules, FE-34) states, taken from
// docs/game/turing-duel-rules.md (DOC-08). The page interpolates them into its
// texts and the scoring module computes with them. `npm run rules:check` fails
// when a value here and the rules file disagree.

/** A room holds up to 5 participants (section 2). Labels run Player 1 … Player 5. */
export const MAX_PARTICIPANTS = 5;
export const FIRST_LABEL = 1;
export const LAST_LABEL = MAX_PARTICIPANTS;

/** At least 1 participant is a human (section 2). */
export const MIN_HUMANS = 1;

/** Bots per room: none, or 1 to 4 (section 8). */
export const MIN_BOTS_WHEN_ANY = 1;
export const MAX_BOTS = MAX_PARTICIPANTS - MIN_HUMANS;

/** One room timer from room creation, never restarts (section 3). */
export const ROOM_TIMER_MINUTES = 3;

/** "Start now" and the timer start the game with 2 or more participants (section 3). */
export const MIN_PARTICIPANTS_TO_START = 2;
/** "Start now" is shown while the room has 2 to 4 participants. */
export const START_NOW_MAX_PARTICIPANTS = MAX_PARTICIPANTS - 1;
/** The timer runs out with only 1 participant: the room closes. */
export const ROOM_CLOSES_WITH_PARTICIPANTS = MIN_PARTICIPANTS_TO_START - 1;

/** Phase durations (sections 4 and 5). */
export const DISCUSSION_SECONDS = 120;
export const VOTING_SECONDS = 45;

/** Every other participant starts marked "human"; there is no "no guess" (section 5). */
export const DEFAULT_MARK = "human";

/** Points per guess (section 6). */
export const POINTS_CORRECT = 1;
export const POINTS_WRONG = -1;

/** From 2 humans on, the top score wins (section 6). */
export const RELATIVE_OUTCOME_MIN_HUMANS = 2;
/** With 1 human: above 0 wins, exactly 0 draws, below 0 loses (section 6). */
export const SINGLE_HUMAN_THRESHOLD = 0;
