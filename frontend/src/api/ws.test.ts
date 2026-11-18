import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebSocketClient } from "./ws";

const flushPromises = async () => {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve();
  }
};

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  public readyState = MockWebSocket.CONNECTING;
  public url: string;
  public onopen: ((event: unknown) => void) | null = null;
  public onmessage: ((event: { data: string }) => void) | null = null;
  public onclose: ((event: { code: number; reason: string }) => void) | null =
    null;
  public onerror: ((event: unknown) => void) | null = null;
  public sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) {
      this.onopen({});
    }
  }

  simulateMessage(data: unknown): void {
    if (this.onmessage) {
      this.onmessage({
        data: typeof data === "string" ? data : JSON.stringify(data),
      });
    }
  }

  simulateClose(code = 1006, reason = "Abnormal"): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose({ code, reason });
    }
  }

  send(data: string): void {
    this.sentMessages.push(data);
  }

  close(code = 1000, reason = "Normal"): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose({ code, reason });
    }
  }
}

describe("WebSocketClient (FE-22)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("fetches ticket and connects to wss://<host>/ws?ticket=", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_abc_123");
    const client = new WebSocketClient({
      fetchTicket,
      url: "wss://api.wozu.test/ws",
    });

    expect(client.getState()).toBe("offline");

    const connectPromise = client.connect();
    await Promise.resolve();
    await connectPromise;

    expect(fetchTicket).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances.length).toBe(1);

    const ws = MockWebSocket.instances[0];
    expect(ws.url).toBe("wss://api.wozu.test/ws?ticket=ticket_abc_123");

    // Simulate connection open
    ws.simulateOpen();
    expect(client.getState()).toBe("connected");
  });

  it("starts heartbeat ping every 25s upon connection", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_ping");
    const client = new WebSocketClient({ fetchTicket });

    await client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    expect(ws.sentMessages).toEqual([]);

    // Advance 25 seconds
    vi.advanceTimersByTime(25_000);
    expect(ws.sentMessages).toEqual([JSON.stringify({ type: "ping" })]);

    // Advance another 25 seconds
    vi.advanceTimersByTime(25_000);
    expect(ws.sentMessages).toEqual([
      JSON.stringify({ type: "ping" }),
      JSON.stringify({ type: "ping" }),
    ]);

    // Server sends pong
    ws.simulateMessage({ type: "pong", payload: null });
    expect(client.getState()).toBe("connected");
  });

  it("routes events by type and ignores unknown types", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_router");
    const client = new WebSocketClient({ fetchTicket });

    const presenceHandler = vi.fn();
    const messageHandler = vi.fn();

    const unsubPresence = client.subscribe("presence", presenceHandler);
    client.subscribe("message", messageHandler);

    await client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    // Send presence event
    ws.simulateMessage({
      type: "presence",
      payload: { user_id: 42, is_online: true },
    });
    expect(presenceHandler).toHaveBeenCalledWith({
      user_id: 42,
      is_online: true,
    });
    expect(messageHandler).not.toHaveBeenCalled();

    // Send message event
    ws.simulateMessage({
      type: "message",
      payload: { id: 101, text: "Hello team" },
    });
    expect(messageHandler).toHaveBeenCalledWith({
      id: 101,
      text: "Hello team",
    });

    // Send unknown event
    ws.simulateMessage({
      type: "unknown_future_event",
      payload: { foo: "bar" },
    });
    // Unknown type should be ignored without error
    expect(presenceHandler).toHaveBeenCalledTimes(1);
    expect(messageHandler).toHaveBeenCalledTimes(1);

    // Unsubscribe presence
    unsubPresence();
    ws.simulateMessage({
      type: "presence",
      payload: { user_id: 42, is_online: false },
    });
    expect(presenceHandler).toHaveBeenCalledTimes(1); // not called again
  });

  it("reconnects with backoff (1s, 2s, 5s, 10s) and acquires new ticket each time", async () => {
    let ticketCounter = 1;
    const fetchTicket = vi.fn().mockImplementation(() => {
      return Promise.resolve(`ticket_${ticketCounter++}`);
    });

    const client = new WebSocketClient({
      fetchTicket,
      reconnectDelays: [1000, 2000, 5000, 10000],
    });

    await client.connect();
    expect(fetchTicket).toHaveBeenCalledTimes(1);

    const ws1 = MockWebSocket.instances[0];
    ws1.simulateOpen();
    expect(client.getState()).toBe("connected");

    // 1st Disconnect: should transition to reconnecting and schedule retry after 1s
    ws1.simulateClose(1011, "Server lost redis");
    expect(client.getState()).toBe("reconnecting");

    // Advance 999ms: not yet reconnected
    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances.length).toBe(1);

    // Advance to 1000ms: 1st reconnect fires
    vi.advanceTimersByTime(1);
    await flushPromises();
    expect(MockWebSocket.instances.length).toBe(2);
    expect(fetchTicket).toHaveBeenCalledTimes(2);

    const ws2 = MockWebSocket.instances[1];
    expect(ws2.url).toContain("ticket_2");

    // 2nd Disconnect: retry after 2s
    ws2.simulateClose(1008, "Invalid ticket");
    expect(client.getState()).toBe("reconnecting");
    vi.advanceTimersByTime(2000);
    await flushPromises();
    expect(MockWebSocket.instances.length).toBe(3);
    expect(fetchTicket).toHaveBeenCalledTimes(3);

    const ws3 = MockWebSocket.instances[2];
    expect(ws3.url).toContain("ticket_3");

    // 3rd Disconnect: retry after 5s
    ws3.simulateClose(1006, "Network drop");
    expect(client.getState()).toBe("reconnecting");
    vi.advanceTimersByTime(5000);
    await flushPromises();
    expect(MockWebSocket.instances.length).toBe(4);
    expect(fetchTicket).toHaveBeenCalledTimes(4);

    // 4th Disconnect: retry after 10s
    const ws4 = MockWebSocket.instances[3];
    ws4.simulateClose(1006, "Network drop");
    vi.advanceTimersByTime(10000);
    await flushPromises();
    expect(MockWebSocket.instances.length).toBe(5);
    expect(fetchTicket).toHaveBeenCalledTimes(5);
  });

  it("does not reconnect when manually disconnected with disconnect()", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_clean");
    const client = new WebSocketClient({ fetchTicket });

    await client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    expect(client.getState()).toBe("connected");

    client.disconnect();
    expect(client.getState()).toBe("offline");

    // Fast-forward timers to ensure no reconnect triggered
    vi.advanceTimersByTime(60_000);
    expect(MockWebSocket.instances.length).toBe(1);
    expect(client.getState()).toBe("offline");
  });

  it("invalidates active TanStack queries after reconnecting", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_queries");
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const client = new WebSocketClient({
      fetchTicket,
      queryClient,
      reconnectDelays: [1000],
    });

    // Initial connection: does not invalidate on first connect
    await client.connect();
    const ws1 = MockWebSocket.instances[0];
    ws1.simulateOpen();
    expect(invalidateSpy).not.toHaveBeenCalled();

    // Disconnect and reconnect
    ws1.simulateClose(1006, "Drop");
    vi.advanceTimersByTime(1000);
    await flushPromises();

    const ws2 = MockWebSocket.instances[1];
    ws2.simulateOpen();

    // After reconnection, active queries are invalidated and refetched
    expect(invalidateSpy).toHaveBeenCalledWith({
      type: "active",
      refetchType: "active",
    });
  });

  it("notifies state listeners on state transitions", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_state");
    const client = new WebSocketClient({ fetchTicket, reconnectDelays: [500] });

    const stateHistory: string[] = [];
    client.onStateChange((state) => stateHistory.push(state));

    expect(stateHistory).toEqual(["offline"]);

    await client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();
    expect(stateHistory).toEqual(["offline", "connected"]);

    ws.simulateClose(1006, "Network drop");
    expect(stateHistory).toEqual(["offline", "connected", "reconnecting"]);

    client.disconnect();
    expect(stateHistory).toEqual([
      "offline",
      "connected",
      "reconnecting",
      "offline",
    ]);
  });

  it("sends frame with top-level fields matching contract", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_send");
    const client = new WebSocketClient({ fetchTicket });

    expect(client.send("chat", { text: "hello" })).toBe(false);

    await client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    expect(client.send("chat", { text: "hello" })).toBe(true);
    expect(ws.sentMessages).toEqual([
      JSON.stringify({ type: "chat", text: "hello" }),
    ]);

    expect(client.send("delivered", { message_id: 6 })).toBe(true);
    expect(ws.sentMessages[1]).toBe(
      JSON.stringify({ type: "delivered", message_id: 6 }),
    );
  });

  it("handles malformed JSON frames and handler exceptions gracefully", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_resilient");
    const client = new WebSocketClient({ fetchTicket });

    const brokenHandler = vi.fn().mockImplementation(() => {
      throw new Error("Handler exploded");
    });
    const goodHandler = vi.fn();

    client.subscribe("notice", brokenHandler);
    client.subscribe("notice", goodHandler);

    await client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    // Send malformed non-JSON
    expect(() => ws.simulateMessage("NOT_JSON_DATA")).not.toThrow();

    // Send valid frame - broken handler should not prevent good handler from running
    expect(() =>
      ws.simulateMessage({ type: "notice", payload: "ok" }),
    ).not.toThrow();
    expect(brokenHandler).toHaveBeenCalledWith("ok");
    expect(goodHandler).toHaveBeenCalledWith("ok");
  });

  it("prevents duplicate concurrent sockets when connect() is called in parallel", async () => {
    let resolveTicket: (val: string) => void = () => {};
    const fetchTicket = vi.fn().mockImplementation(
      () =>
        new Promise<string>((resolve) => {
          resolveTicket = resolve;
        }),
    );
    const client = new WebSocketClient({ fetchTicket });

    // Two connect calls in parallel while ticket is pending
    const c1 = client.connect();
    const c2 = client.connect();

    resolveTicket("ticket_concurrency");
    await Promise.all([c1, c2]);

    expect(fetchTicket).toHaveBeenCalledTimes(1);
    expect(MockWebSocket.instances.length).toBe(1);
  });

  it("handles rapid connect(); disconnect(); connect(); without leaking sockets", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_rapid");
    const client = new WebSocketClient({ fetchTicket });

    void client.connect();
    client.disconnect();
    await client.connect();

    const openInstances = MockWebSocket.instances.filter(
      (s) => s.readyState === MockWebSocket.OPEN,
    );
    expect(openInstances.length).toBeLessThanOrEqual(1);
  });

  it("resets backoff ladder upon receiving pong heartbeat", async () => {
    let count = 1;
    const fetchTicket = vi
      .fn()
      .mockImplementation(() => Promise.resolve(`ticket_${count++}`));
    const client = new WebSocketClient({
      fetchTicket,
      reconnectDelays: [1000, 2000, 5000],
    });

    await client.connect();
    const ws1 = MockWebSocket.instances[0];
    ws1.simulateOpen();

    // Drop immediately
    ws1.simulateClose(1008);
    vi.advanceTimersByTime(1000);
    await flushPromises();

    const ws2 = MockWebSocket.instances[1];
    ws2.simulateOpen();

    // Pong arrives, proving socket is good
    ws2.simulateMessage({ type: "pong" });

    // Close again: because pong reset the ladder, next retry delay is 1000ms instead of climbing
    ws2.simulateClose(1006);
    expect(client.getState()).toBe("reconnecting");
    vi.advanceTimersByTime(1000);
    await flushPromises();
    expect(MockWebSocket.instances.length).toBe(3);
  });

  it("allows setting QueryClient post-construction", async () => {
    const fetchTicket = vi.fn().mockResolvedValue("ticket_post");
    const queryClient = new QueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const client = new WebSocketClient({ fetchTicket, reconnectDelays: [100] });
    client.setQueryClient(queryClient);

    await client.connect();
    const ws1 = MockWebSocket.instances[0];
    ws1.simulateOpen();

    ws1.simulateClose(1006);
    vi.advanceTimersByTime(100);
    await flushPromises();

    const ws2 = MockWebSocket.instances[1];
    ws2.simulateOpen();

    expect(invalidateSpy).toHaveBeenCalledWith({
      type: "active",
      refetchType: "active",
    });
  });
});
