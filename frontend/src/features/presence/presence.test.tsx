import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebSocketClient } from "../../api/ws";
import { ConversationCard } from "../conversations/ConversationCard";
import type { ConversationItem } from "../conversations/types";
import { PresenceDot } from "./PresenceDot";
import { presenceStore, PresenceStore } from "./presenceStore";
import { useUserPresence } from "./usePresence";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe("PresenceStore (FE-12)", () => {
  let store: PresenceStore;

  beforeEach(() => {
    vi.useFakeTimers();
    store = new PresenceStore(1500);
  });

  afterEach(() => {
    store.reset();
    vi.useRealTimers();
  });

  it("returns fallback status when not seeded", () => {
    expect(store.getPresence(42, false)).toBe(false);
    expect(store.getPresence(42, true)).toBe(true);
  });

  it("seeds initial presence and does not overwrite live event state", () => {
    store.seed(1, true);
    expect(store.getPresence(1)).toBe(true);

    // Live event sets to false
    store.setPresence(1, false, { immediate: true });
    expect(store.getPresence(1)).toBe(false);

    // Stale REST seed attempt should be ignored
    store.seed(1, true);
    expect(store.getPresence(1)).toBe(false);
  });

  it("seeds multiple friends via seedFromFriends", () => {
    store.seedFromFriends([
      { user_id: 10, is_online: true },
      { user_id: 11, is_online: false },
    ]);
    expect(store.getPresence(10)).toBe(true);
    expect(store.getPresence(11)).toBe(false);
  });

  it("immediately marks user online and notifies subscribers", () => {
    const listener = vi.fn();
    store.subscribe(5, listener);

    store.setPresence(5, true);

    expect(store.getPresence(5)).toBe(true);
    expect(listener).toHaveBeenCalledWith(true);
  });

  it("debounces offline transition to prevent flicker on quick reconnects", () => {
    const listener = vi.fn();
    store.setPresence(7, true);
    store.subscribe(7, listener);

    // Disconnect event arrives
    store.setPresence(7, false);

    // Immediately after, it should still be online (debouncing)
    expect(store.getPresence(7)).toBe(true);
    expect(listener).not.toHaveBeenCalledWith(false);

    // Fast-forward half the debounce time (750ms)
    vi.advanceTimersByTime(750);
    expect(store.getPresence(7)).toBe(true);

    // User reconnects within debounce window
    store.setPresence(7, true);

    // Advance beyond original debounce window
    vi.advanceTimersByTime(1000);

    // Status never dropped to false!
    expect(store.getPresence(7)).toBe(true);
    expect(listener).not.toHaveBeenCalledWith(false);
  });

  it("transitions to offline after debounce timer expires", () => {
    const listener = vi.fn();
    store.setPresence(8, true);
    store.subscribe(8, listener);

    store.setPresence(8, false);
    expect(store.getPresence(8)).toBe(true);

    // Advance full debounce time (1500ms)
    vi.advanceTimersByTime(1500);

    expect(store.getPresence(8)).toBe(false);
    expect(listener).toHaveBeenCalledWith(false);
  });

  it("supports immediate offline transition", () => {
    const listener = vi.fn();
    store.setPresence(9, true);
    store.subscribe(9, listener);

    store.setPresence(9, false, { immediate: true });

    expect(store.getPresence(9)).toBe(false);
    expect(listener).toHaveBeenCalledWith(false);
  });

  it("handles incoming WebSocket presence events", () => {
    const mockWs = new WebSocketClient();
    store.initWebSocketListener(mockWs);

    const listener = vi.fn();
    store.subscribe(20, listener);

    // Simulate WS frame: { type: "presence", payload: { user_id: 20, is_online: true } }
    mockWs["handleMessage"](
      JSON.stringify({
        type: "presence",
        payload: { user_id: 20, is_online: true },
      }),
    );

    expect(store.getPresence(20)).toBe(true);
    expect(listener).toHaveBeenCalledWith(true);
  });
});

describe("useUserPresence Hook & UI Components (FE-12)", () => {
  let root: Root;
  let container: HTMLDivElement;
  let testStore: PresenceStore;

  beforeEach(() => {
    testStore = new PresenceStore(1500);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    testStore.reset();
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  const TestPresenceComponent: React.FC<{
    userId?: number;
    initialOnline?: boolean;
  }> = ({ userId, initialOnline }) => {
    const isOnline = useUserPresence(userId, initialOnline, testStore);
    return (
      <div data-testid="presence-wrapper">
        <PresenceDot isOnline={isOnline} showLabel={true} />
      </div>
    );
  };

  it("renders PresenceDot with label and reflects live store updates", async () => {
    await act(async () => {
      root.render(<TestPresenceComponent userId={100} initialOnline={true} />);
    });

    const dot = container.querySelector('[data-testid="presence-dot"]');
    const label = container.querySelector('[data-testid="presence-label"]');

    expect(dot).not.toBeNull();
    expect(dot?.classList.contains("bg-emerald-500")).toBe(true);
    expect(label?.textContent).toBe("online");

    // Update presence live
    await act(async () => {
      testStore.setPresence(100, false, { immediate: true });
    });

    expect(dot?.classList.contains("bg-gray-400")).toBe(true);
    expect(label?.textContent).toBe("offline");
  });

  it("renders ConversationCard with peer presence dot and updates live", async () => {
    const mockConversation: ConversationItem = {
      id: 1,
      type: "direct",
      title: null,
      job_id: null,
      job_title: null,
      last_message_id: null,
      last_message_content: null,
      last_message_author_id: null,
      unread_count: 0,
      updated_at: new Date().toISOString(),
      peer: {
        id: 50,
        display_name: "Alice Smith",
        avatar_url: "/avatars/alice.png",
      },
    };

    // Pre-seed user 50 as offline in the singleton store
    await act(async () => {
      root.render(
        <ConversationCard conversation={mockConversation} onClick={vi.fn()} />,
      );
    });

    const dot = container.querySelector('[data-testid="presence-dot-50"]');
    expect(dot).not.toBeNull();
    expect(dot?.classList.contains("bg-gray-400")).toBe(true);

    // Live update peer 50 to online
    await act(async () => {
      presenceStore.setPresence(50, true);
    });

    expect(dot?.classList.contains("bg-emerald-500")).toBe(true);
  });
});
