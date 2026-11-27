/**
 * Types for Turing Duel game lobby and room (FE-31, FE-32).
 *
 * Per docs/game/turing-duel-rules.md (section 9 — No bot leak), every participant
 * payload before results exposes strictly { id, display_label, is_you } with no
 * user_id, avatar, or bot flag.
 */

export type GameRoomState =
  "waiting" | "discussion" | "voting" | "finished" | "closed";

export interface RoomParticipant {
  id: number;
  display_label: string;
  is_you: boolean;
}

export interface GameRoom {
  id: number;
  state: GameRoomState;
  target_size: number;
  participant_count: number;
  my_participant_id: number;
  room_expires_at: string | null;
  phase_ends_at: string | null;
  participants: RoomParticipant[];
}

export interface QueueJoinResponse {
  message: string;
  room_id: number;
}

export interface GameParticipantEventPayload {
  room_id: number;
  participant: {
    id: number;
    display_label: string;
  };
  participant_count: number;
  room_expires_at: string | null;
}

export interface GameStartedEventPayload {
  room_id: number;
  state: string;
  phase_ends_at: string;
}

export interface GameRoomClosedEventPayload {
  room_id: number;
}

export interface GameChatMessage {
  id: number;
  participant_id: number;
  display_label: string;
  text: string;
}

export interface GameMessagesResponse {
  items: GameChatMessage[];
  prev_before_id?: number | null;
}

export type VoteGuess = "bot" | "human";

export interface GameVoteRequest {
  target_participant_id: number;
  guess: VoteGuess;
}

export interface GameVoteResponse {
  target_participant_id: number;
  guess: VoteGuess;
}

export interface SavedVote {
  target_participant_id: number;
  guess: VoteGuess;
}

export type ParticipantOutcome = "win" | "draw" | "loss";

export interface ParticipantResult {
  participant_id: number;
  display_label: string;
  is_bot: boolean;
  score: number | null;
  outcome: ParticipantOutcome | null;
  deception_rate: number | null;
}

export interface GameResultsResponse {
  room_id: number;
  state: "finished";
  my_participant_id: number;
  winner_participant_ids: number[];
  is_draw: boolean;
  participants: ParticipantResult[];
}

export interface GameSnapshotPayload {
  room: GameRoom;
  messages: GameChatMessage[];
  my_votes: SavedVote[];
}

export interface GamePhaseVotingEventPayload {
  room_id: number;
  state: "voting";
  phase_ends_at: string;
}

export interface GamePhaseFinishedEventPayload {
  room_id: number;
  state: "finished";
  phase_ends_at: null;
}
