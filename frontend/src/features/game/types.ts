/**
 * Types for Turing Duel game lobby and waiting room (FE-31).
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
