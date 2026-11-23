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
  private wsStateUnsubscribe: (() => void) | null = null;
  private debounceMs: number;
  private eventSequence = 0;
  private userEventEpoch = new Map<number, number>();

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
    this.userEventEpoch.set(userId, ++this.eventSequence);
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
      if (this.status.get(userId) === false) {
        return;
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
   * Reconcile presence snapshot from /friends or custom fetcher without overwriting
   * newer live WebSocket events received while the request was in-flight.
   */
  public async reconcile(
    fetcher?: () => Promise<FriendPresenceItem[]>,
  ): Promise<void> {
    const requestSeq = ++this.eventSequence;
    try {
      const friends = fetcher
        ? await fetcher()
        : await apiClient<FriendPresenceItem[]>("/friends");
      if (!Array.isArray(friends)) return;

      for (const friend of friends) {
        if (!friend || typeof friend.user_id !== "number") continue;
        const uid = friend.user_id;
        const lastEvent = this.userEventEpoch.get(uid) ?? 0;
        if (lastEvent > requestSeq) {
          // A newer live event arrived while this snapshot was in-flight. Skip!
          continue;
        }

        const nextStatus = Boolean(friend.is_online);
        const current = this.status.get(uid);

        if (current !== nextStatus) {
          const timer = this.debounceTimers.get(uid);
          if (timer) {
            clearTimeout(timer);
            this.debounceTimers.delete(uid);
          }
          this.status.set(uid, nextStatus);
          this.notify(uid, nextStatus);
        }
      }
    } catch {
      // Reconcile is background best-effort
    }
  }

  /**
   * Attach listener to WebSocket "presence" event and reconnect lifecycle.
   */
  public initWebSocketListener(client: WebSocketClient = wsClient): () => void {
    if (this.wsUnsubscribe) {
      this.wsUnsubscribe();
      this.wsUnsubscribe = null;
    }
    if (this.wsStateUnsubscribe) {
      this.wsStateUnsubscribe();
      this.wsStateUnsubscribe = null;
    }

    this.wsUnsubscribe = client.subscribe<PresenceEventPayload>(
      "presence",
      (payload) => {
        if (!payload || typeof payload.user_id !== "number") return;
        this.setPresence(payload.user_id, Boolean(payload.is_online));
      },
    );

    let hadDisconnect = false;
    this.wsStateUnsubscribe = client.onStateChange((state) => {
      if (state === "reconnecting" || state === "offline") {
        hadDisconnect = true;
      } else if (state === "connected" && hadDisconnect) {
        hadDisconnect = false;
        void this.reconcile();
      }
    });

    return () => {
      if (this.wsUnsubscribe) {
        this.wsUnsubscribe();
        this.wsUnsubscribe = null;
      }
      if (this.wsStateUnsubscribe) {
        this.wsStateUnsubscribe();
        this.wsStateUnsubscribe = null;
      }
    };
  }

  /**
   * Fetch friends list via REST to seed initial online statuses.
   */
  public async fetchAndSeedFriends(): Promise<void> {
    await this.reconcile();
  }

  public reset(): void {
    if (this.wsUnsubscribe) {
      this.wsUnsubscribe();
      this.wsUnsubscribe = null;
    }
    if (this.wsStateUnsubscribe) {
      this.wsStateUnsubscribe();
      this.wsStateUnsubscribe = null;
    }
    for (const timer of this.debounceTimers.values()) {
      clearTimeout(timer);
    }
    this.debounceTimers.clear();
    this.status.clear();
    this.listeners.clear();
    this.hasLiveEvent.clear();
    this.userEventEpoch.clear();
    this.eventSequence = 0;
  }
}

export const presenceStore = new PresenceStore();
