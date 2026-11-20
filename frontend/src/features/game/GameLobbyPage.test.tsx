import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ApiError, clearTokens, setTokens } from "../../api/client";
import {
  wsClient,
  type WsConnectionState,
  type WsEventHandler,
} from "../../api/ws";
import { gameApi } from "./api";
import { GameLobbyPage } from "./GameLobbyPage";
import type { GameRoom } from "./types";

let root: Root;
let container: HTMLDivElement;
const wsHandlers = new Map<string, Set<WsEventHandler<unknown>>>();

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function emitWs(type: string, payload: unknown) {
  const set = wsHandlers.get(type);
  if (!set) return;
  for (const handler of set) handler(payload);
}

function makeRoom(overrides: Partial<GameRoom> = {}): GameRoom {
  const expiresAt = new Date(Date.now() + 180_000).toISOString();
  return {
    id: 42,
    state: "waiting",
    target_size: 5,
    participant_count: 1,
    my_participant_id: 2,
    room_expires_at: expiresAt,
    phase_ends_at: null,
    participants: [{ id: 2, display_label: "Player 2", is_you: true }],
    ...overrides,
  };
}

beforeEach(() => {
  wsHandlers.clear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);

  vi.spyOn(wsClient, "subscribe").mockImplementation((type, handler) => {
    let set = wsHandlers.get(type);
    if (!set) {
      set = new Set();
      wsHandlers.set(type, set);
    }
    set.add(handler);
    return () => {
      wsHandlers.get(type)?.delete(handler);
    };
  });
  vi.spyOn(wsClient, "getState").mockReturnValue("connected");
  vi.spyOn(wsClient, "onStateChange").mockReturnValue(() => {
    /* noop */
  });
});

afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function renderLobby() {
  const router = createMemoryRouter(
    [
      { path: "/game", element: <GameLobbyPage /> },
      {
        path: "/game/rooms/:id",
        element: <div data-testid="active-game-room">Room screen</div>,
      },
      {
        path: "/game/rules",
        element: <div data-testid="rules-screen">Rules screen</div>,
      },
    ],
    { initialEntries: ["/game"] },
  );
  await act(async () => {
    root.render(<RouterProvider router={router} />);
  });
  return router;
}

async function clickTestId(testId: string) {
  const el = container.querySelector<HTMLButtonElement>(
    `[data-testid="${testId}"]`,
  );
  if (!el) throw new Error(`Element [data-testid="${testId}"] not found`);
  await act(async () => {
    el.click();
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

test("lobby renders rules summary, link to /game/rules, and Find a game button", async () => {
  await renderLobby();

  expect(container.textContent).toContain("How a match works");
  const rulesLink = container.querySelector<HTMLAnchorElement>(
    'a[href="/game/rules"]',
  );
  expect(rulesLink).not.toBeNull();
  expect(
    container.querySelector('[data-testid="find-game-btn"]'),
  ).not.toBeNull();
});

test("Find a game enters waiting room with anonymous seats, N/5 count, timer, and Start now only at 2–4", async () => {
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 42,
  });
  vi.spyOn(gameApi, "getRoom").mockResolvedValue(makeRoom());
  const leaveSpy = vi.spyOn(gameApi, "leaveQueue").mockResolvedValue(undefined);

  await renderLobby();
  await clickTestId("find-game-btn");

  expect(
    container.querySelector('[data-testid="participant-count"]')?.textContent,
  ).toContain("1 / 5");
  expect(
    container.querySelector('[data-testid="room-countdown"]')?.textContent,
  ).toMatch(/^0[23]:\d{2}$/);
  // Start now hidden at 1 participant
  expect(container.querySelector('[data-testid="start-now-btn"]')).toBeNull();

  // Only anonymous Player labels — no avatars, no profile links, no bot labels
  const seat2 = container.querySelector('[data-testid="participant-seat-2"]');
  expect(seat2?.textContent).toContain("Player 2");
  expect(seat2?.textContent).toContain("You");
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector('a[href^="/users/"]')).toBeNull();

  // Live join brings participant count to 2 -> Start now becomes visible
  await act(async () => {
    emitWs("game_participant_joined", {
      room_id: 42,
      participant: { id: 5, display_label: "Player 5" },
      participant_count: 2,
      room_expires_at: null,
    });
  });

  expect(
    container.querySelector('[data-testid="participant-count"]')?.textContent,
  ).toContain("2 / 5");
  expect(
    container.querySelector('[data-testid="participant-seat-5"]')?.textContent,
  ).toBe("Player 5");
  expect(
    container.querySelector('[data-testid="start-now-btn"]'),
  ).not.toBeNull();

  // Live leave drops count back to 1 -> Start now disappears
  await act(async () => {
    emitWs("game_participant_left", {
      room_id: 42,
      participant: { id: 5, display_label: "Player 5" },
      participant_count: 1,
      room_expires_at: null,
    });
  });

  expect(
    container.querySelector('[data-testid="participant-count"]')?.textContent,
  ).toContain("1 / 5");
  expect(
    container.querySelector('[data-testid="participant-seat-5"]'),
  ).toBeNull();
  expect(container.querySelector('[data-testid="start-now-btn"]')).toBeNull();

  // Leaving via unmount automatically calls DELETE /game/queue/leave
  await act(() => root.unmount());
  expect(leaveSpy).toHaveBeenCalledTimes(1);
});

test("Start now navigates to /game/rooms/:id and handles concurrent 409 race gracefully", async () => {
  const room = makeRoom({
    participant_count: 3,
    participants: [
      { id: 2, display_label: "Player 2", is_you: true },
      { id: 4, display_label: "Player 4", is_you: false },
      { id: 5, display_label: "Player 5", is_you: false },
    ],
  });
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 42,
  });
  vi.spyOn(gameApi, "getRoom")
    .mockResolvedValueOnce(room)
    .mockResolvedValueOnce({ ...room, state: "discussion" });
  const startSpy = vi
    .spyOn(gameApi, "startRoom")
    .mockRejectedValueOnce(new ApiError(409, "409", "Room already started"));
  const leaveSpy = vi.spyOn(gameApi, "leaveQueue").mockResolvedValue(undefined);

  const router = await renderLobby();
  await clickTestId("find-game-btn");
  await clickTestId("start-now-btn");

  expect(startSpy).toHaveBeenCalledWith(42);
  expect(router.state.location.pathname).toBe("/game/rooms/42");
  // Transitioning into started game must NOT leave the room
  expect(leaveSpy).not.toHaveBeenCalled();
});

test("game_started WS event navigates to /game/rooms/:id without leaving", async () => {
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 77,
  });
  vi.spyOn(gameApi, "getRoom").mockResolvedValue(makeRoom({ id: 77 }));
  const leaveSpy = vi.spyOn(gameApi, "leaveQueue").mockResolvedValue(undefined);

  const router = await renderLobby();
  await clickTestId("find-game-btn");

  await act(async () => {
    emitWs("game_started", {
      room_id: 77,
      state: "discussion",
      phase_ends_at: new Date(Date.now() + 120_000).toISOString(),
    });
  });

  expect(router.state.location.pathname).toBe("/game/rooms/77");
  expect(leaveSpy).not.toHaveBeenCalled();
});

test("game_room_closed returns player to lobby with notice and re-enables Find a game", async () => {
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 88,
  });
  vi.spyOn(gameApi, "getRoom").mockResolvedValue(makeRoom({ id: 88 }));

  await renderLobby();
  await clickTestId("find-game-btn");

  await act(async () => {
    emitWs("game_room_closed", { room_id: 88 });
  });

  expect(
    container.querySelector('[data-testid="room-closed-notice"]')?.textContent,
  ).toContain("Nobody else joined");
  expect(
    container.querySelector('[data-testid="find-game-btn"]'),
  ).not.toBeNull();
});

test("Leave waiting room button calls leaveQueue and returns cleanly to lobby", async () => {
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 91,
  });
  vi.spyOn(gameApi, "getRoom").mockResolvedValue(makeRoom({ id: 91 }));
  const leaveSpy = vi.spyOn(gameApi, "leaveQueue").mockResolvedValue(undefined);

  await renderLobby();
  await clickTestId("find-game-btn");
  await clickTestId("leave-room-btn");

  expect(leaveSpy).toHaveBeenCalledTimes(1);
  expect(
    container.querySelector('[data-testid="find-game-btn"]'),
  ).not.toBeNull();
});

test("logging out while waiting leaves the room with the captured access token", async () => {
  setTokens({
    accessToken: "lobby-jwt-token",
    refreshToken: "lobby-refresh-token",
  });
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 95,
  });
  vi.spyOn(gameApi, "getRoom").mockResolvedValue(makeRoom({ id: 95 }));
  const leaveSpy = vi.spyOn(gameApi, "leaveQueue").mockResolvedValue(undefined);

  await renderLobby();
  await clickTestId("find-game-btn");
  expect(
    container.querySelector('[data-testid="game-waiting-room"]'),
  ).not.toBeNull();

  await act(async () => {
    clearTokens();
  });

  expect(leaveSpy).toHaveBeenCalledTimes(1);
  expect(leaveSpy).toHaveBeenCalledWith("lobby-jwt-token");
  expect(
    container.querySelector('[data-testid="find-game-btn"]'),
  ).not.toBeNull();
});

test("joinQueue returning 409 shows match already started error and does not render leave button", async () => {
  vi.spyOn(gameApi, "joinQueue").mockRejectedValue(
    new ApiError(409, "409", "Active room already in progress"),
  );

  await renderLobby();
  await clickTestId("find-game-btn");

  expect(container.textContent).toContain("Your match has already started.");
  expect(
    container.querySelector('[data-testid="find-game-btn"]'),
  ).not.toBeNull();
  expect(container.textContent).not.toContain("Leave previous room");
});

test("pagehide event leaves queue and pageshow with persisted resets waiting room view", async () => {
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 61,
  });
  vi.spyOn(gameApi, "getRoom").mockResolvedValue(makeRoom({ id: 61 }));
  const leaveSpy = vi.spyOn(gameApi, "leaveQueue").mockResolvedValue(undefined);

  await renderLobby();
  await clickTestId("find-game-btn");
  expect(
    container.querySelector('[data-testid="game-waiting-room"]'),
  ).not.toBeNull();

  // Dispatch pagehide
  await act(async () => {
    window.dispatchEvent(new Event("pagehide"));
  });
  expect(leaveSpy).toHaveBeenCalledTimes(1);
  expect(
    container.querySelector('[data-testid="game-waiting-room"]'),
  ).toBeNull();

  // Dispatch pageshow with persisted (bfcache return)
  await act(async () => {
    const pageShowEvent = new Event("pageshow") as PageTransitionEvent;
    Object.defineProperty(pageShowEvent, "persisted", { value: true });
    window.dispatchEvent(pageShowEvent);
  });
  expect(
    container.querySelector('[data-testid="game-waiting-room"]'),
  ).toBeNull();
  expect(
    container.querySelector('[data-testid="find-game-btn"]'),
  ).not.toBeNull();
});

test("reconnect resync returning 403 resets waiting room view to lobby", async () => {
  let stateCallback: ((state: WsConnectionState) => void) | undefined;
  vi.spyOn(wsClient, "getState").mockReturnValue("reconnecting");
  vi.spyOn(wsClient, "onStateChange").mockImplementation((cb) => {
    stateCallback = cb;
    return () => {};
  });

  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 63,
  });
  vi.spyOn(gameApi, "getRoom")
    .mockResolvedValueOnce(makeRoom({ id: 63 }))
    .mockRejectedValueOnce(new ApiError(403, "403", "Forbidden"));

  await renderLobby();
  await clickTestId("find-game-btn");
  expect(
    container.querySelector('[data-testid="game-waiting-room"]'),
  ).not.toBeNull();

  // Simulate WS reconnect
  await act(async () => {
    stateCallback?.("connected");
  });

  expect(
    container.querySelector('[data-testid="game-waiting-room"]'),
  ).toBeNull();
  expect(
    container.querySelector('[data-testid="find-game-btn"]'),
  ).not.toBeNull();
});

test("participant joins are sorted by display_label", async () => {
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 65,
  });
  vi.spyOn(gameApi, "getRoom").mockResolvedValue(
    makeRoom({
      id: 65,
      participants: [{ id: 3, display_label: "Player 3", is_you: true }],
    }),
  );

  await renderLobby();
  await clickTestId("find-game-btn");

  // Player 1 joins out-of-order
  await act(async () => {
    emitWs("game_participant_joined", {
      room_id: 65,
      participant: { id: 1, display_label: "Player 1" },
      participant_count: 2,
      room_expires_at: null,
    });
  });

  const seats = Array.from(container.querySelectorAll(".game-seat")).map(
    (el) => el.textContent,
  );
  expect(seats[0]).toContain("Player 1");
  expect(seats[1]).toContain("Player 3");
});

test("if getRoom fails right after joinQueue, leaves queue cleanly", async () => {
  vi.spyOn(gameApi, "joinQueue").mockResolvedValue({
    message: "queued",
    room_id: 67,
  });
  vi.spyOn(gameApi, "getRoom").mockRejectedValue(new Error("Network glitch"));
  const leaveSpy = vi.spyOn(gameApi, "leaveQueue").mockResolvedValue(undefined);

  await renderLobby();
  await clickTestId("find-game-btn");

  expect(leaveSpy).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("We couldn’t join a room right now.");
});
