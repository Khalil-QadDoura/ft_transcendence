import { apiClient } from "../../api/client";
import type {
  GameMessagesResponse,
  GameResultsResponse,
  GameRoom,
  GameVoteResponse,
  QueueJoinResponse,
  VoteGuess,
} from "./types";

export const gameApi = {
  async joinQueue(): Promise<QueueJoinResponse> {
    return apiClient<QueueJoinResponse>("/game/queue/join", {
      method: "POST",
      signal: AbortSignal.timeout(15_000),
    });
  },

  async leaveQueue(accessToken?: string): Promise<void> {
    await apiClient<void>("/game/queue/leave", {
      method: "DELETE",
      keepalive: true,
      ...(accessToken
        ? {
            skipAuth: true,
            headers: { Authorization: `Bearer ${accessToken}` },
          }
        : {}),
      signal: AbortSignal.timeout(15_000),
    });
  },

  async getRoom(roomId: number, signal?: AbortSignal): Promise<GameRoom> {
    return apiClient<GameRoom>(`/game/rooms/${roomId}`, {
      method: "GET",
      signal: signal ?? AbortSignal.timeout(15_000),
    });
  },

  async getActiveRoom(signal?: AbortSignal): Promise<GameRoom | null> {
    return apiClient<GameRoom | null>("/game/rooms/active", {
      method: "GET",
      signal: signal ?? AbortSignal.timeout(15_000),
    });
  },

  async startRoom(roomId: number): Promise<GameRoom> {
    return apiClient<GameRoom>(`/game/rooms/${roomId}/start`, {
      method: "POST",
      signal: AbortSignal.timeout(15_000),
    });
  },

  async getRoomMessages(
    roomId: number,
    options?: { beforeId?: number; limit?: number; signal?: AbortSignal },
  ): Promise<GameMessagesResponse> {
    const params = new URLSearchParams();
    if (options?.beforeId !== undefined) {
      params.set("before_id", String(options.beforeId));
    }
    if (options?.limit !== undefined) {
      params.set("limit", String(options.limit));
    }
    const qs = params.toString();
    return apiClient<GameMessagesResponse>(
      `/game/rooms/${roomId}/messages${qs ? `?${qs}` : ""}`,
      {
        method: "GET",
        signal: options?.signal ?? AbortSignal.timeout(15_000),
      },
    );
  },

  async castVote(
    roomId: number,
    targetParticipantId: number,
    guess: VoteGuess,
    signal?: AbortSignal,
  ): Promise<GameVoteResponse> {
    return apiClient<GameVoteResponse>(`/game/rooms/${roomId}/votes`, {
      method: "POST",
      body: JSON.stringify({
        target_participant_id: targetParticipantId,
        guess,
      }),
      signal: signal ?? AbortSignal.timeout(15_000),
    });
  },

  async getResults(
    roomId: number,
    signal?: AbortSignal,
  ): Promise<GameResultsResponse> {
    return apiClient<GameResultsResponse>(`/game/rooms/${roomId}/results`, {
      method: "GET",
      signal: signal ?? AbortSignal.timeout(15_000),
    });
  },
};
