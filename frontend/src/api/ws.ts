/**
 * WebSocket Client for WOZU Web (ft_transcendence)
 * Card FE-22: Build the WebSocket client: ticket auth, reconnect, event routing
 *
 * Protocol & Rules (docs/api/api-contract.md → "WebSocket protocol"):
 * - Ticket Auth: Access tokens never appear in the WebSocket URL. Every connection
 *   and reconnection obtains a single-use ticket via POST /api/ws/ticket (valid 30s).
 * - Single Socket per Tab: One persistent socket per tab on /ws.
 * - Heartbeat: Ping sent every 25 seconds ({"type": "ping"}); server acknowledges with pong.
 * - Reconnect Backoff: Exponential backoff on disconnect: 1s, 2s, 5s, then capped at 10s.
 *   Each reconnect requests a fresh ticket via POST /api/ws/ticket.
 * - Close Codes:
 *   - 1008: Invalid/expired ticket or password changed (token_version). Reconnects with a fresh ticket.
 *   - 1011: Server lost Redis connection. Reconnects with backoff.
 *   - 1000: Clean manual client closure. Does not reconnect.
 * - Cache Invalidation: After reconnecting, visible TanStack queries are invalidated and refetched,
 *   as live events sent while offline are not replayed.
 * - Event Router: Subscriptions partitioned by `type`. Unknown types are safely ignored.
 */

import { QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiClient } from "./client";

export type WsConnectionState = "connected" | "reconnecting" | "offline";

export interface WsEvent<T = unknown> {
  type: string;
  payload?: T;
}

export type WsEventHandler<T = unknown> = (payload: T) => void;

export interface WsClientOptions {
  /** Override the ticket fetching function (defaults to apiClient POST /ws/ticket) */
  fetchTicket?: () => Promise<string>;
  /** Custom base WebSocket URL (defaults to wss://<host>/ws or ws://<host>/ws) */
  url?: string;
  /** Reconnection backoff intervals in milliseconds (default: [1000, 2000, 5000, 10000]) */
  reconnectDelays?: number[];
  /** Ping interval in milliseconds (default: 25_000 ms) */
  pingIntervalMs?: number;
  /** TanStack QueryClient to invalidate active queries upon reconnect */
  queryClient?: QueryClient;
}

const DEFAULT_RECONNECT_DELAYS = [1000, 2000, 5000, 10000];
const DEFAULT_PING_INTERVAL_MS = 25_000;

export class WebSocketClient {
  private socket: WebSocket | null = null;
  private state: WsConnectionState = "offline";
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private backoffResetTimer: ReturnType<typeof setTimeout> | null = null;
  private connectPromise: Promise<void> | null = null;
  private connectionGeneration = 0;
  private isManuallyClosed = false;
  private hasConnectedOnce = false;

  private listeners = new Map<string, Set<WsEventHandler<unknown>>>();
  private stateListeners = new Set<(state: WsConnectionState) => void>();
  private queryClient: QueryClient | null = null;
  private options: WsClientOptions;

  constructor(options: WsClientOptions = {}) {
    this.options = options;
    if (options.queryClient) {
      this.queryClient = options.queryClient;
    }
  }

  /**
   * Attach or update the TanStack QueryClient used to invalidate visible data on reconnect.
   */
  public setQueryClient(client: QueryClient | null): void {
    this.queryClient = client;
  }

  /**
   * Current connection state: "connected" | "reconnecting" | "offline".
   */
  public getState(): WsConnectionState {
    return this.state;
  }

  /**
   * Subscribe to connection state changes. Returns an unsubscribe callback.
   */
  public onStateChange(
    listener: (state: WsConnectionState) => void,
  ): () => void {
    this.stateListeners.add(listener);
    listener(this.state);
    return () => {
      this.stateListeners.delete(listener);
    };
  }

  private setState(newState: WsConnectionState): void {
    if (this.state !== newState) {
      this.state = newState;
      for (const listener of this.stateListeners) {
        try {
          listener(newState);
        } catch (e) {
          console.error("Error in WsClient state listener:", e);
        }
      }
    }
  }

  /**
   * Register an event handler for a specific event type.
   * Unknown incoming events are ignored. Returns an unsubscribe callback.
   */
  public subscribe<T = unknown>(
    type: string,
    handler: WsEventHandler<T>,
  ): () => void {
    let handlers = this.listeners.get(type);
    if (!handlers) {
      handlers = new Set();
      this.listeners.set(type, handlers);
    }
    handlers.add(handler as WsEventHandler<unknown>);

    return () => {
      const currentHandlers = this.listeners.get(type);
      if (currentHandlers) {
        currentHandlers.delete(handler as WsEventHandler<unknown>);
        if (currentHandlers.size === 0) {
          this.listeners.delete(type);
        }
      }
    };
  }

  /**
   * Calculate the reconnection delay based on the backoff ladder: 1s, 2s, 5s, then 10s.
   */
  public getReconnectDelay(attempt: number): number {
    const ladder = this.options.reconnectDelays ?? DEFAULT_RECONNECT_DELAYS;
    const index = Math.min(attempt, ladder.length - 1);
    return ladder[index];
  }

  /**
   * Obtain a fresh one-time ticket via POST /api/ws/ticket.
   */
  private async getTicket(): Promise<string> {
    if (this.options.fetchTicket) {
      return this.options.fetchTicket();
    }
    const response = await apiClient<{ ticket: string }>("/ws/ticket", {
      method: "POST",
    });
    return response.ticket;
  }

  /**
   * Resolve target WebSocket URL based on ticket, host, and protocol.
   */
  private resolveUrl(ticket: string): string {
    const protocol =
      typeof window !== "undefined" && window.location.protocol === "https:"
        ? "wss:"
        : "ws:";
    const host =
      typeof window !== "undefined" ? window.location.host : "localhost";

    if (this.options.url) {
      const delimiter = this.options.url.includes("?") ? "&" : "?";
      return `${this.options.url}${delimiter}ticket=${encodeURIComponent(ticket)}`;
    }

    return `${protocol}//${host}/ws?ticket=${encodeURIComponent(ticket)}`;
  }

  /**
   * Open the WebSocket connection using a fresh single-use ticket.
   */
  public async connect(): Promise<void> {
    this.isManuallyClosed = false;

    // Do not reconnect if already open or connecting
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.CONNECTING ||
        this.socket.readyState === WebSocket.OPEN)
    ) {
      return;
    }

    if (this.connectPromise) {
      return this.connectPromise;
    }

    this.clearTimers();

    if (this.reconnectAttempt > 0) {
      this.setState("reconnecting");
    }

    const currentGen = ++this.connectionGeneration;

    this.connectPromise = (async () => {
      try {
        const ticket = await this.getTicket();
        if (this.isManuallyClosed || this.connectionGeneration !== currentGen) {
          return;
        }

        if (this.socket) {
          const old = this.socket;
          this.socket = null;
          old.close(1000, "Superseded");
        }

        const wsUrl = this.resolveUrl(ticket);
        const ws = new WebSocket(wsUrl);
        this.socket = ws;

        ws.onopen = () => {
          if (this.socket !== ws || this.connectionGeneration !== currentGen) {
            ws.close();
            return;
          }

          const isReconnection = this.hasConnectedOnce;
          this.hasConnectedOnce = true;
          this.setState("connected");

          this.startPing();
          this.scheduleBackoffReset(ws);

          // Invalidate and refetch visible TanStack queries after reconnection
          if (isReconnection && this.queryClient) {
            this.queryClient.invalidateQueries({
              type: "active",
              refetchType: "active",
            });
          }
        };

        ws.onmessage = (event: MessageEvent) => {
          if (this.socket !== ws) return;
          this.handleMessage(event.data);
        };

        ws.onclose = (event: CloseEvent) => {
          if (this.socket !== ws) return;
          this.handleClose(event);
        };

        ws.onerror = () => {
          // WebSocket error is handled via onclose callback
        };
      } catch {
        // Failed to acquire ticket or establish socket: schedule reconnect
        if (
          !this.isManuallyClosed &&
          this.connectionGeneration === currentGen
        ) {
          this.scheduleReconnect();
        }
      } finally {
        if (this.connectionGeneration === currentGen) {
          this.connectPromise = null;
        }
      }
    })();

    return this.connectPromise;
  }

  private scheduleBackoffReset(ws: WebSocket): void {
    if (this.backoffResetTimer) {
      clearTimeout(this.backoffResetTimer);
    }
    this.backoffResetTimer = setTimeout(() => {
      if (this.socket === ws && ws.readyState === WebSocket.OPEN) {
        this.reconnectAttempt = 0;
      }
    }, 2000);
  }

  /**
   * Parse incoming frame and route to registered subscribers by type.
   * Unknown event types are safely ignored.
   */
  private handleMessage(data: unknown): void {
    if (typeof data !== "string") return;

    try {
      const frame = JSON.parse(data) as WsEvent & Record<string, unknown>;
      if (!frame || typeof frame.type !== "string") return;

      // Ping/Pong heartbeat response
      if (frame.type === "pong") {
        this.reconnectAttempt = 0;
        return;
      }

      const handlers = this.listeners.get(frame.type);
      if (handlers && handlers.size > 0) {
        const payload = frame.payload !== undefined ? frame.payload : frame;
        for (const handler of handlers) {
          try {
            handler(payload);
          } catch (err) {
            console.error(
              `Error in handler for ws event [${frame.type}]:`,
              err,
            );
          }
        }
      }
    } catch {
      // Discard non-JSON frames
    }
  }

  /**
   * Handle socket closure:
   * - If manually closed: transition to offline.
   * - Otherwise: schedule reconnection with backoff ladder.
   */
  private handleClose(event: CloseEvent): void {
    this.stopPing();
    this.socket = null;

    if (this.isManuallyClosed || event.code === 1000) {
      this.setState("offline");
      return;
    }

    this.scheduleReconnect();
  }

  /**
   * Schedule reconnection with backoff: 1s, 2s, 5s, then every 10s.
   */
  private scheduleReconnect(): void {
    this.setState("reconnecting");
    const delay = this.getReconnectDelay(this.reconnectAttempt);
    this.reconnectAttempt += 1;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.isManuallyClosed) {
        this.connect();
      }
    }, delay);
  }

  /**
   * Send JSON frame over the socket with top-level fields matching the contract.
   */
  public send(type: string, payload?: unknown): boolean {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      const frame =
        payload && typeof payload === "object" && !Array.isArray(payload)
          ? { type, ...(payload as Record<string, unknown>) }
          : payload !== undefined
            ? { type, payload }
            : { type };
      this.socket.send(JSON.stringify(frame));
      return true;
    }
    return false;
  }

  /**
   * Start periodic heartbeat ping (every 25 seconds).
   */
  private startPing(): void {
    this.stopPing();
    const interval = this.options.pingIntervalMs ?? DEFAULT_PING_INTERVAL_MS;
    this.pingTimer = setInterval(() => {
      this.send("ping");
    }, interval);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private clearTimers(): void {
    this.stopPing();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  /**
   * Cleanly disconnect and terminate reconnection attempts.
   */
  public disconnect(): void {
    this.isManuallyClosed = true;
    this.connectionGeneration++;
    this.connectPromise = null;
    this.clearTimers();
    if (this.backoffResetTimer) {
      clearTimeout(this.backoffResetTimer);
      this.backoffResetTimer = null;
    }
    if (this.socket) {
      // Avoid firing reconnect on manual disconnect
      const s = this.socket;
      this.socket = null;
      s.close(1000, "Clean client disconnect");
    }
    this.setState("offline");
  }
}

/**
 * Global singleton WebSocket client for app-wide use.
 */
export const wsClient = new WebSocketClient();

/**
 * React Hook: Listen to live WebSocket connection state ("connected" | "reconnecting" | "offline").
 */
export function useWsStatus(
  client: WebSocketClient = wsClient,
): WsConnectionState {
  const [state, setState] = useState<WsConnectionState>(() =>
    client.getState(),
  );

  useEffect(() => {
    return client.onStateChange((nextState) => {
      setState(nextState);
    });
  }, [client]);

  return state;
}

/**
 * React Hook: Subscribe to a specific WebSocket event type.
 */
export function useWsEvent<T = unknown>(
  type: string,
  handler: WsEventHandler<T>,
  client: WebSocketClient = wsClient,
): void {
  useEffect(() => {
    return client.subscribe<T>(type, handler);
  }, [type, handler, client]);
}
