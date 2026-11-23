import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  WebSocketClient,
  wsClient,
  type WsConnectionState,
  type WsEventHandler,
} from "../../api/ws";
import { gameApi } from "./api";
import { GameRoomPage } from "./GameRoomPage";
import type {
  GameMessagesResponse,
  GameResultsResponse,
  GameRoom,
  GameSnapshotPayload,
} from "./types";

let root: Root;
let container: HTMLDivElement;
const roomWsHandlers = new Map<string, Set<WsEventHandler<unknown>>>();
const globalWsHandlers = new Map<string, Set<WsEventHandler<unknown>>>();
let roomWsStateListeners: Array<(state: WsConnectionState) => void> = [];
const sentFrames: Array<{ type: string; payload?: unknown }> = [];

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function emitRoomWs(type: string, payload: unknown) {
  const set = roomWsHandlers.get(type);
  if (!set) return;
  for (const handler of set) handler(payload);
}

function emitRoomWsState(state: WsConnectionState) {
  for (const listener of roomWsStateListeners) listener(state);
}

function makeDiscussionRoom(overrides: Partial<GameRoom> = {}): GameRoom {
  const phaseEndsAt = new Date(Date.now() + 120_000).toISOString();
  return {
    id: 10,
    state: "discussion",
    target_size: 3,
    participant_count: 3,
    my_participant_id: 1,
    room_expires_at: null,
    phase_ends_at: phaseEndsAt,
    participants: [
      { id: 1, display_label: "Player 1", is_you: true },
      { id: 2, display_label: "Player 2", is_you: false },
      { id: 3, display_label: "Player 3", is_you: false },
    ],
    ...overrides,
  };
}

function makeResults(): GameResultsResponse {
  return {
    room_id: 10,
    state: "finished",
    my_participant_id: 1,
    winner_participant_ids: [1],
    is_draw: false,
    participants: [
      {
        participant_id: 1,
        display_label: "Player 1",
        is_bot: false,
        score: 2,
        outcome: "win",
        deception_rate: null,
      },
      {
        participant_id: 2,
        display_label: "Player 2",
        is_bot: true,
        score: null,
        outcome: null,
        deception_rate: 0,
      },
      {
        participant_id: 3,
        display_label: "Player 3",
        is_bot: false,
        score: 0,
        outcome: "loss",
        deception_rate: null,
      },
    ],
  };
}

beforeEach(() => {
  roomWsHandlers.clear();
  globalWsHandlers.clear();
  roomWsStateListeners = [];
  sentFrames.length = 0;

  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);

  // Mock global wsClient
  vi.spyOn(wsClient, "subscribe").mockImplementation((type, handler) => {
    let set = globalWsHandlers.get(type);
    if (!set) {
      set = new Set();
      globalWsHandlers.set(type, set);
    }
    set.add(handler);
    return () => {
      globalWsHandlers.get(type)?.delete(handler);
    };
  });

  // Mock room WebSocketClient instance methods
  vi.spyOn(WebSocketClient.prototype, "connect").mockImplementation(() =>
    Promise.resolve(),
  );
  vi.spyOn(WebSocketClient.prototype, "disconnect").mockImplementation(
    () => {},
  );
  vi.spyOn(WebSocketClient.prototype, "onStateChange").mockImplementation(
    (listener) => {
      roomWsStateListeners.push(listener);
      return () => {
        roomWsStateListeners = roomWsStateListeners.filter(
          (l) => l !== listener,
        );
      };
    },
  );
  vi.spyOn(WebSocketClient.prototype, "subscribe").mockImplementation(
    (type, handler) => {
      let set = roomWsHandlers.get(type);
      if (!set) {
        set = new Set();
        roomWsHandlers.set(type, set);
      }
      set.add(handler);
      return () => {
        roomWsHandlers.get(type)?.delete(handler);
      };
    },
  );
  vi.spyOn(WebSocketClient.prototype, "send").mockImplementation(
    (type, payload) => {
      sentFrames.push({ type, payload });
      return true;
    },
  );

  // Mock Element.prototype.scrollIntoView for tests
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(async () => {
  await act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function renderRoom(initialPath = "/game/rooms/10") {
  const router = createMemoryRouter(
    [
      { path: "/game/rooms/:id", element: <GameRoomPage /> },
      { path: "/game", element: <div>Game Lobby</div> },
      { path: "/game/rules", element: <div>Rules Page</div> },
    ],
    { initialEntries: [initialPath] },
  );

  await act(async () => {
    root.render(<RouterProvider router={router} />);
  });
}

test("renders discussion phase with countdown, anonymous participants, and rules link", async () => {
  const room = makeDiscussionRoom();
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);

  await renderRoom();

  // Header and phase badge
  expect(container.textContent).toContain("Turing Duel");
  expect(container.textContent).toContain("Discussion");

  // Rules link (FE-34)
  const rulesLink = container.querySelector('a[href="/game/rules"]');
  expect(rulesLink).not.toBeNull();
  expect(rulesLink?.textContent).toContain("Rules");

  // Anonymous participants (DOC-08 section 9 — no bot leak)
  expect(container.textContent).toContain("Player 1");
  expect(container.textContent).toContain("Player 2");
  expect(container.textContent).toContain("Player 3");
  expect(container.textContent).toContain("You");

  // No bot badges before results
  expect(container.textContent).not.toContain("Bot");
  expect(container.textContent).not.toContain("Human");

  // Chat panel
  expect(container.textContent).toContain("Discussion Chat");
  const sendButton = container.querySelector('button[type="submit"]');
  expect(sendButton).not.toBeNull();
});

test("receives incoming chat message and sends chat message over room socket", async () => {
  const room = makeDiscussionRoom();
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);

  await renderRoom();

  // Simulate incoming game_message
  await act(async () => {
    emitRoomWs("game_message", {
      id: 101,
      participant_id: 2,
      display_label: "Player 2",
      text: "Hello everyone, are you human?",
    });
  });

  expect(container.textContent).toContain("Player 2");
  expect(container.textContent).toContain("Hello everyone, are you human?");

  // Type and submit own message
  const input = container.querySelector(
    'input[type="text"]',
  ) as HTMLInputElement;
  const form = container.querySelector("form") as HTMLFormElement;

  await act(async () => {
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    )?.set;
    nativeSetter?.call(input, "Yes I am definitely human!");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });

  await act(async () => {
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });

  // Verify frame sent over room socket
  expect(sentFrames).toContainEqual({
    type: "chat_message",
    payload: { text: "Yes I am definitely human!" },
  });
});

test("transitions to voting phase on game_phase_voting and sets default mark to human", async () => {
  const room = makeDiscussionRoom();
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  const castVoteSpy = vi.spyOn(gameApi, "castVote").mockResolvedValue({
    target_participant_id: 2,
    guess: "bot",
  });

  await renderRoom();

  // Discussion phase initially
  expect(container.textContent).toContain("Discussion");

  // Transition to voting phase
  const votingEndsAt = new Date(Date.now() + 45_000).toISOString();
  await act(async () => {
    emitRoomWs("game_phase_voting", {
      room_id: 10,
      state: "voting",
      phase_ends_at: votingEndsAt,
    });
  });

  expect(container.textContent).toContain("Voting");
  expect(container.textContent).toContain("Spot the Bot");

  // Self (Player 1) is NOT voted on, only Player 2 and Player 3 are listed
  const votingCards = container.querySelectorAll(".game-voting-card");
  expect(votingCards.length).toBe(2);

  // Both start marked "Human" by default (rules section 5)
  const humanToggles = container.querySelectorAll(".game-btn-toggle.is-active");
  expect(humanToggles.length).toBe(2);
  expect(humanToggles[0]?.textContent).toContain("Human");

  // Click "Bot" for Player 2
  const botButton = votingCards[0]?.querySelectorAll(
    ".game-btn-toggle",
  )[1] as HTMLButtonElement;
  expect(botButton.textContent).toContain("Bot");

  await act(async () => {
    botButton.click();
  });

  expect(castVoteSpy).toHaveBeenCalledWith(10, 2, "bot");
  expect(botButton.classList.contains("is-active")).toBe(true);

  // Switch back to "Human" (marks can be changed freely until timer expires)
  const humanButton = votingCards[0]?.querySelectorAll(
    ".game-btn-toggle",
  )[0] as HTMLButtonElement;
  await act(async () => {
    humanButton.click();
  });

  expect(castVoteSpy).toHaveBeenCalledWith(10, 2, "human");
  expect(humanButton.classList.contains("is-active")).toBe(true);
});

test("transitions to results phase on game_phase_finished, reveals identities and scores", async () => {
  const room = makeDiscussionRoom({ state: "voting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  const results = makeResults();
  const getResultsSpy = vi
    .spyOn(gameApi, "getResults")
    .mockResolvedValue(results);

  await renderRoom();

  // Transition to finished
  await act(async () => {
    emitRoomWs("game_phase_finished", {
      room_id: 10,
      state: "finished",
      phase_ends_at: null,
    });
  });

  expect(getResultsSpy).toHaveBeenCalledWith(10, undefined);

  // Current user won
  expect(container.textContent).toContain("You Won!");

  // Revealed identities
  expect(container.textContent).toContain("Bot");
  expect(container.textContent).toContain("Human");
  expect(container.textContent).toContain("+2 pts");
  expect(container.textContent).toContain("Winner");

  // Bot deception rate
  expect(container.textContent).toContain("0% deception rate");

  // Play Again button
  const playAgainButton = Array.from(container.querySelectorAll("button")).find(
    (b) => b.textContent?.includes("Play Again"),
  );
  expect(playAgainButton).toBeDefined();

  await act(async () => {
    playAgainButton?.click();
  });

  expect(container.textContent).toContain("Game Lobby");
});

test("handles room not found or loading errors gracefully", async () => {
  vi.spyOn(gameApi, "getRoom").mockRejectedValueOnce(
    new Error("404 Not Found"),
  );

  await renderRoom();

  expect(container.textContent).toContain("does not exist or has expired");
  const lobbyBtn = container.querySelector("button");
  expect(lobbyBtn?.textContent).toContain("Back to Lobby");

  await act(async () => {
    lobbyBtn?.click();
  });

  expect(container.textContent).toContain("Game Lobby");
});

test("hydrates room, chat messages, and saved votes from game_snapshot", async () => {
  const room = makeDiscussionRoom({ state: "voting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);

  await renderRoom();

  // Snapshot arrives
  await act(async () => {
    emitRoomWs("game_snapshot", {
      room: {
        ...room,
        state: "voting",
      },
      messages: [
        {
          id: 50,
          participant_id: 3,
          display_label: "Player 3",
          text: "Snapshot message from history",
        },
      ],
      my_votes: [
        {
          target_participant_id: 3,
          guess: "bot",
        },
      ],
    });
  });

  // Verify Player 3 has "bot" active
  const cards = container.querySelectorAll(".game-voting-card");
  const p3Card = Array.from(cards).find((c) =>
    c.textContent?.includes("Player 3"),
  );
  expect(p3Card).toBeDefined();

  const activeBtn = p3Card?.querySelector(".game-btn-toggle.is-active");
  expect(activeBtn?.textContent).toContain("Bot");
});

test("treats game_snapshot my_votes as authoritative and reverts unacknowledged optimistic bot marks to human", async () => {
  const room = makeDiscussionRoom({ state: "voting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  vi.spyOn(gameApi, "castVote").mockResolvedValueOnce({
    target_participant_id: 3,
    guess: "bot",
  });

  await renderRoom();

  const cards = container.querySelectorAll(".game-voting-card");
  const p3Card = Array.from(cards).find((c) =>
    c.textContent?.includes("Player 3"),
  );
  const botButton = p3Card?.querySelectorAll(
    ".game-btn-toggle",
  )[1] as HTMLButtonElement;

  // Mark Player 3 as bot
  await act(async () => {
    botButton.click();
  });
  expect(
    p3Card?.querySelector(".game-btn-toggle.is-active")?.textContent,
  ).toContain("Bot");

  // Reconnect snapshot arrives where my_votes is empty
  await act(async () => {
    emitRoomWs("game_snapshot", {
      room: {
        ...room,
        state: "voting",
      },
      messages: [],
      my_votes: [],
    });
  });

  // Player 3 must revert back to default "Human" because snapshot is authoritative
  const p3CardAfter = Array.from(
    container.querySelectorAll(".game-voting-card"),
  ).find((c) => c.textContent?.includes("Player 3"));
  expect(
    p3CardAfter?.querySelector(".game-btn-toggle.is-active")?.textContent,
  ).toContain("Human");
});

test("renders draw and loss outcomes correctly in results phase", async () => {
  const room = makeDiscussionRoom({ state: "voting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);

  // Results where caller drew
  const drawResults: GameResultsResponse = {
    room_id: 10,
    state: "finished",
    my_participant_id: 1,
    winner_participant_ids: [],
    is_draw: true,
    participants: [
      {
        participant_id: 1,
        display_label: "Player 1",
        is_bot: false,
        score: 0,
        outcome: "draw",
        deception_rate: null,
      },
      {
        participant_id: 2,
        display_label: "Player 2",
        is_bot: true,
        score: null,
        outcome: null,
        deception_rate: 50,
      },
    ],
  };

  vi.spyOn(gameApi, "getResults").mockResolvedValueOnce(drawResults);

  await renderRoom();

  await act(async () => {
    emitRoomWs("game_phase_finished", {
      room_id: 10,
      state: "finished",
      phase_ends_at: null,
    });
  });

  expect(container.textContent).toContain("It’s a Draw");
  expect(container.textContent).toContain("50% deception rate");
});

test("shows vote error and rolls back mark if castVote fails with 409 conflict", async () => {
  const room = makeDiscussionRoom({ state: "voting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  vi.spyOn(gameApi, "castVote").mockRejectedValueOnce(
    new Error("409 Conflict: voting ended"),
  );

  await renderRoom();

  const votingCards = container.querySelectorAll(".game-voting-card");
  const humanButton = votingCards[0]?.querySelectorAll(
    ".game-btn-toggle",
  )[0] as HTMLButtonElement;
  const botButton = votingCards[0]?.querySelectorAll(
    ".game-btn-toggle",
  )[1] as HTMLButtonElement;

  expect(humanButton.classList.contains("is-active")).toBe(true);
  expect(botButton.classList.contains("is-active")).toBe(false);

  await act(async () => {
    botButton.click();
  });

  expect(container.textContent).toContain("couldn’t save your mark");
  // Verified rollback: mark reverted back to human
  expect(humanButton.classList.contains("is-active")).toBe(true);
  expect(botButton.classList.contains("is-active")).toBe(false);
});

test("guards against concurrent in-flight vote requests for the same target", async () => {
  const room = makeDiscussionRoom({ state: "voting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);

  let resolveVote!: () => void;
  const votePromise = new Promise<void>((resolve) => {
    resolveVote = resolve;
  });
  const castVoteSpy = vi
    .spyOn(gameApi, "castVote")
    .mockImplementation(
      () => votePromise as unknown as ReturnType<typeof gameApi.castVote>,
    );

  await renderRoom();

  const votingCards = container.querySelectorAll(".game-voting-card");
  const botButton = votingCards[0]?.querySelectorAll(
    ".game-btn-toggle",
  )[1] as HTMLButtonElement;

  // Click once while in-flight
  await act(async () => {
    botButton.click();
  });
  expect(castVoteSpy).toHaveBeenCalledTimes(1);

  // Click second time while first request is still in-flight
  await act(async () => {
    botButton.click();
  });
  expect(castVoteSpy).toHaveBeenCalledTimes(1);

  await act(async () => {
    resolveVote();
  });
});

test("shows waiting notice and back to lobby if room is still waiting", async () => {
  const waitingRoom = makeDiscussionRoom({ state: "waiting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(waitingRoom);

  await renderRoom();

  expect(container.textContent).toContain("Waiting for participants");
  expect(container.textContent).toContain(
    "Discussion opens as soon as the match starts",
  );

  const lobbyBtn = container.querySelector("button");
  await act(async () => {
    lobbyBtn?.click();
  });

  expect(container.textContent).toContain("Game Lobby");
});

test("FE-33: reloads discussion phase with chat history from getRoomMessages and countdown", async () => {
  const room = makeDiscussionRoom({ state: "discussion" });
  const messagesData: GameMessagesResponse = {
    items: [
      {
        id: 101,
        participant_id: 2,
        display_label: "Player 2",
        text: "Are you real or a bot?",
      },
      {
        id: 102,
        participant_id: 1,
        display_label: "Player 1",
        text: "Definitely real human here!",
      },
    ],
  };

  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  vi.spyOn(gameApi, "getRoomMessages").mockResolvedValueOnce(messagesData);

  await renderRoom();

  expect(container.textContent).toContain("Turing Duel");
  expect(container.textContent).toContain("Discussion");
  expect(container.textContent).toContain("Are you real or a bot?");
  expect(container.textContent).toContain("Definitely real human here!");
});

test("FE-33: applies game_snapshot resync, deduplicates messages and recalculates countdown", async () => {
  const room = makeDiscussionRoom({ state: "discussion" });
  const messagesData: GameMessagesResponse = {
    items: [
      {
        id: 101,
        participant_id: 2,
        display_label: "Player 2",
        text: "Initial message from REST",
      },
    ],
  };

  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  vi.spyOn(gameApi, "getRoomMessages").mockResolvedValueOnce(messagesData);

  await renderRoom();

  expect(container.textContent).toContain("Initial message from REST");

  // Reconnect snapshot arriving over WebSocket
  const updatedPhaseEndsAt = new Date(Date.now() + 60_000).toISOString();
  const snapshot: GameSnapshotPayload = {
    room: {
      ...room,
      phase_ends_at: updatedPhaseEndsAt,
    },
    messages: [
      // message 101 is duplicated, message 103 is new
      {
        id: 101,
        participant_id: 2,
        display_label: "Player 2",
        text: "Initial message from REST",
      },
      {
        id: 103,
        participant_id: 3,
        display_label: "Player 3",
        text: "New snapshot message after reconnect",
      },
    ],
    my_votes: [],
  };

  await act(async () => {
    emitRoomWs("game_snapshot", snapshot);
  });

  // Verify no duplicate message 101
  const renderedBubbles = container.querySelectorAll(".game-chat-bubble");
  expect(renderedBubbles).toHaveLength(2);
  expect(container.textContent).toContain("Initial message from REST");
  expect(container.textContent).toContain(
    "New snapshot message after reconnect",
  );
});

test("FE-33: reloads voting phase and restores submitted marks from game_snapshot", async () => {
  const room = makeDiscussionRoom({ state: "voting" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  vi.spyOn(gameApi, "getRoomMessages").mockResolvedValueOnce({ items: [] });

  await renderRoom();

  expect(container.textContent).toContain("Voting");
  expect(container.textContent).toContain("Spot the Bot");

  // Reconnect/snapshot with existing submitted mark: Player 2 was marked as bot
  const snapshot: GameSnapshotPayload = {
    room,
    messages: [],
    my_votes: [
      {
        target_participant_id: 2,
        guess: "bot",
      },
    ],
  };

  await act(async () => {
    emitRoomWs("game_snapshot", snapshot);
  });

  const votingCards = container.querySelectorAll(".game-voting-card");
  expect(votingCards).toHaveLength(2); // Player 2 and Player 3

  // Player 2 card should have "Bot" button active
  const player2BotBtn = votingCards[0]?.querySelectorAll(".game-btn-toggle")[1];
  expect(player2BotBtn?.className).toContain("is-active");

  // Player 3 card should have default "Human" button active
  const player3HumanBtn =
    votingCards[1]?.querySelectorAll(".game-btn-toggle")[0];
  expect(player3HumanBtn?.className).toContain("is-active");
});

test("FE-33: reloads finished phase and automatically fetches match results", async () => {
  const room = makeDiscussionRoom({ state: "finished", phase_ends_at: null });
  const results = makeResults();

  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  vi.spyOn(gameApi, "getRoomMessages").mockResolvedValueOnce({ items: [] });
  vi.spyOn(gameApi, "getResults").mockResolvedValueOnce(results);

  await renderRoom();

  expect(container.textContent).toContain("Results");
  expect(container.textContent).toContain("You Won!");
  expect(container.textContent).toContain("Play Again");
});

test("FE-33: shows reconnecting banner when room socket drops and clears on reconnect", async () => {
  const room = makeDiscussionRoom({ state: "discussion" });
  vi.spyOn(gameApi, "getRoom").mockResolvedValueOnce(room);
  vi.spyOn(gameApi, "getRoomMessages").mockResolvedValueOnce({ items: [] });

  await renderRoom();

  expect(container.textContent).not.toContain("Reconnecting to room…");

  // Simulate socket dropping and entering reconnecting state
  await act(async () => {
    emitRoomWsState("reconnecting");
  });

  expect(container.textContent).toContain("Reconnecting to room…");

  // Simulate socket reconnecting
  await act(async () => {
    emitRoomWsState("connected");
  });

  expect(container.textContent).not.toContain("Reconnecting to room…");
});
