import { apiClient } from "../../api/client";
import { wsClient, type WebSocketClient } from "../../api/ws";
import type {
  FriendPresenceItem,
  PresenceEventPayload,
  PresenceListener,
} from "./types";

export const DEFAULT_PRESENCE_DEBOUNCE_MS = 1500;

export class PresenceStore {
  private status = new Map<number, boolean>();
  private debounceTimers = new Map<number, ReturnType<typeof setTimeout>>();
  private listeners = new Map<number, Set<PresenceListener>>();
  private hasLiveEvent = new Set<number>();
  private wsUnsubscribe: (() => void) | null = null;
  private debounceMs: number;

  constructor(debounceMs = DEFAULT_PRESENCE_DEBOUNCE_MS) {
    this.debounceMs = debounceMs;
  }

  public setDebounceMs(ms: number): void {
    this.debounceMs = ms;
  }

  public getPresence(userId: number, fallback = false): boolean {
    return this.status.get(userId) ?? fallback;
  }

  /**
   * Seed store from REST endpoints (e.g. initial friend list or profile).
   * Live events received via WebSocket take precedence and will not be overwritten by stale REST responses.
   */
  public seed(userId: number, isOnline: boolean): void {
    if (this.hasLiveEvent.has(userId) || this.status.has(userId)) return;
    this.status.set(userId, isOnline);
  }

  public seedFromFriends(friends: FriendPresenceItem[]): void {
    if (!Array.isArray(friends)) return;
    for (const friend of friends) {
      if (friend && typeof friend.user_id === "number") {
        this.seed(friend.user_id, Boolean(friend.is_online));
      }
    }
  }

  /**
   * Update presence based on WebSocket events.
   * Online transitions happen immediately.
   * Offline transitions are debounced to avoid flicker during quick reconnects.
   */
  public setPresence(
    userId: number,
    isOnline: boolean,
    options: { immediate?: boolean } = {},
  ): void {
    this.hasLiveEvent.add(userId);

    if (isOnline) {
      const existingTimer = this.debounceTimers.get(userId);
      if (existingTimer) {
        clearTimeout(existingTimer);
        this.debounceTimers.delete(userId);
      }

      if (this.status.get(userId) === true) {
        return;
      }

      this.status.set(userId, true);
      this.notify(userId, true);
      return;
    }

    // isOnline is false
    if (options.immediate) {
      const existingTimer = this.debounceTimers.get(userId);
      if (existingTimer) {
        clearTimeout(existingTimer);
        this.debounceTimers.delete(userId);
      }
      this.status.set(userId, false);
      this.notify(userId, false);
      return;
    }

    if (this.debounceTimers.has(userId)) {
      return;
    }

    const timer = setTimeout(() => {
      this.debounceTimers.delete(userId);
      this.status.set(userId, false);
      this.notify(userId, false);
    }, this.debounceMs);

    this.debounceTimers.set(userId, timer);
  }

  public subscribe(userId: number, listener: PresenceListener): () => void {
    let userListeners = this.listeners.get(userId);
    if (!userListeners) {
      userListeners = new Set();
      this.listeners.set(userId, userListeners);
    }
    userListeners.add(listener);

    return () => {
      const current = this.listeners.get(userId);
      if (current) {
        current.delete(listener);
        if (current.size === 0) {
          this.listeners.delete(userId);
        }
      }
    };
  }

  private notify(userId: number, isOnline: boolean): void {
    const userListeners = this.listeners.get(userId);
    if (userListeners) {
      for (const listener of userListeners) {
        try {
          listener(isOnline);
        } catch (err) {
          console.error(`Error in presence listener for user ${userId}:`, err);
        }
      }
    }
  }

  /**
   * Attach listener to WebSocket "presence" event.
   */
  public initWebSocketListener(client: WebSocketClient = wsClient): () => void {
    if (this.wsUnsubscribe) {
      this.wsUnsubscribe();
      this.wsUnsubscribe = null;
    }

    this.wsUnsubscribe = client.subscribe<PresenceEventPayload>(
      "presence",
      (payload) => {
        if (!payload || typeof payload.user_id !== "number") return;
        this.setPresence(payload.user_id, Boolean(payload.is_online));
      },
    );

    return () => {
      if (this.wsUnsubscribe) {
        this.wsUnsubscribe();
        this.wsUnsubscribe = null;
      }
    };
  }

  /**
   * Fetch friends list via REST to seed initial online statuses.
   */
  public async fetchAndSeedFriends(): Promise<void> {
    try {
      const friends = await apiClient<FriendPresenceItem[]>("/friends");
      this.seedFromFriends(friends);
    } catch {
      // Non-critical background seed; failure will fall back to per-user REST values
    }
  }

  public reset(): void {
    if (this.wsUnsubscribe) {
      this.wsUnsubscribe();
      this.wsUnsubscribe = null;
    }
    for (const timer of this.debounceTimers.values()) {
      clearTimeout(timer);
    }
    this.debounceTimers.clear();
    this.status.clear();
    this.listeners.clear();
    this.hasLiveEvent.clear();
  }
}

export const presenceStore = new PresenceStore();
