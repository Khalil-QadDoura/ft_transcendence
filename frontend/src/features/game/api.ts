import { apiClient } from "../../api/client";
import type { GameRoom, QueueJoinResponse } from "./types";

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
};
