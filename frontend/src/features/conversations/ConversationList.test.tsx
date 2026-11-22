import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { ConversationList } from "./ConversationList";
import type {
  ConversationItem,
  WsConversationUpdatedPayload,
  WsMessagePayload,
} from "./types";

// Mock the API module
vi.mock("./api", () => ({
  listConversations: vi.fn(),
  getConversation: vi.fn(),
}));

// Mock WebSocket event hook
type WsCallback<T> = (payload: T) => void;
const wsListeners = new Map<string, WsCallback<unknown>>();

vi.mock("../../api/ws", () => ({
  useWsEvent: vi.fn((type: string, handler: WsCallback<unknown>) => {
    wsListeners.set(type, handler);
  }),
}));

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function setNativeValue(
  element: HTMLInputElement | HTMLSelectElement,
  value: string,
) {
  const valueSetter = Object.getOwnPropertyDescriptor(element, "value")?.set;
  const prototype = Object.getPrototypeOf(element);
  const prototypeValueSetter = Object.getOwnPropertyDescriptor(
    prototype,
    "value",
  )?.set;

  if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
    prototypeValueSetter.call(element, value);
  } else if (valueSetter) {
    valueSetter.call(element, value);
  } else {
    element.value = value;
  }
}

const mockConversations: ConversationItem[] = [
  {
    id: 1,
    type: "direct",
    title: null,
    job_id: 10,
    job_title: "Senior Frontend Engineer",
    last_message_id: 101,
    last_message_content: "Looking forward to meeting you!",
    last_message_author_id: 2,
    unread_count: 2,
    updated_at: "2026-11-12T10:00:00Z",
    peer: {
      id: 2,
      display_name: "Sarah Recruiter",
      avatar_url: null,
    },
  },
  {
    id: 2,
    type: "direct",
    title: null,
    job_id: null,
    job_title: null,
    last_message_id: 99,
    last_message_content: "Did you check the pull request?",
    last_message_author_id: 3,
    unread_count: 0,
    updated_at: "2026-11-12T09:00:00Z",
    peer: {
      id: 3,
      display_name: "Khalil Kaddoura",
      avatar_url: "/files/avatars/3/photo.png",
    },
  },
];

describe("ConversationList Component (FE-29)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsListeners.clear();
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it("renders conversations with participant names, avatars, snippets and unread badges", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce(mockConversations);
    const mockOnSelect = vi.fn();

    await act(async () => {
      root.render(<ConversationList onSelectConversation={mockOnSelect} />);
    });

    expect(container.textContent).toContain("Sarah Recruiter");
    expect(container.textContent).toContain("Looking forward to meeting you!");
    expect(container.textContent).toContain("Senior Frontend Engineer");
    expect(
      container.querySelector('[data-testid="unread-badge"]')?.textContent,
    ).toContain("2");

    expect(container.textContent).toContain("Khalil Kaddoura");
    expect(container.textContent).toContain("Did you check the pull request?");
  });

  it("handles clicking a conversation and invokes onSelectConversation", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce(mockConversations);
    const mockOnSelect = vi.fn();

    await act(async () => {
      root.render(<ConversationList onSelectConversation={mockOnSelect} />);
    });

    const card = container.querySelector<HTMLButtonElement>(
      '[data-testid="conversation-card-1"]',
    );
    expect(card).not.toBeNull();

    await act(async () => {
      card?.click();
    });

    expect(mockOnSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 1,
        last_message_content: "Looking forward to meeting you!",
      }),
    );
  });

  it("updates snippet, increments unread count, and bumps conversation to top on WebSocket message", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce([
      ...mockConversations,
    ]);
    const mockOnSelect = vi.fn();

    await act(async () => {
      root.render(<ConversationList onSelectConversation={mockOnSelect} />);
    });

    expect(container.textContent).toContain("Khalil Kaddoura");

    // Simulate real-time message arriving for conversation 2 (currently at index 1)
    const messageHandler = wsListeners.get("message") as
      WsCallback<WsMessagePayload> | undefined;
    expect(messageHandler).toBeDefined();

    await act(async () => {
      messageHandler?.({
        id: 200,
        conversation_id: 2,
        author_id: 3,
        content: "Let's review the WebSocket client together!",
        created_at: "2026-11-12T11:00:00Z",
      });
    });

    expect(container.textContent).toContain(
      "Let's review the WebSocket client together!",
    );

    // Check card order in DOM: conversation 2 should now be first!
    const cards = container.querySelectorAll(
      '[data-testid^="conversation-card-"]',
    );
    expect(cards[0].getAttribute("data-testid")).toBe("conversation-card-2");
    expect(cards[1].getAttribute("data-testid")).toBe("conversation-card-1");
  });

  it("updates unread count when conversation_updated event is received", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce([
      ...mockConversations,
    ]);
    const mockOnSelect = vi.fn();

    await act(async () => {
      root.render(<ConversationList onSelectConversation={mockOnSelect} />);
    });

    expect(
      container.querySelector('[data-testid="unread-badge"]')?.textContent,
    ).toContain("2");

    const updateHandler = wsListeners.get("conversation_updated") as
      WsCallback<WsConversationUpdatedPayload> | undefined;
    expect(updateHandler).toBeDefined();

    await act(async () => {
      updateHandler?.({
        conversation_id: 1,
        unread_count: 0,
      });
    });

    expect(container.querySelector('[data-testid="unread-badge"]')).toBeNull();
  });

  it("resets row unread to 0 and updates header total unread on conversation_updated", async () => {
    const twoUnreadConvs: ConversationItem[] = [
      { ...mockConversations[0], id: 1, unread_count: 1 },
      { ...mockConversations[1], id: 2, unread_count: 1 },
    ];
    vi.mocked(api.listConversations).mockResolvedValueOnce(twoUnreadConvs);

    await act(async () => {
      root.render(<ConversationList onSelectConversation={vi.fn()} />);
    });

    // Both rows have unread badges, and header says 2 unread
    expect(
      container.querySelector('[data-testid="header-unread-count"]')
        ?.textContent,
    ).toContain("2");

    const updateHandler = wsListeners.get("conversation_updated") as
      WsCallback<WsConversationUpdatedPayload> | undefined;
    expect(updateHandler).toBeDefined();

    // User reads conversation 1 -> event arrives with total unread remaining = 1
    await act(async () => {
      updateHandler?.({
        conversation_id: 1,
        unread_count: 1,
      });
    });

    // Row 1 badge should be gone (reset to 0)
    const card1 = container.querySelector(
      '[data-testid="conversation-card-1"]',
    );
    expect(card1?.querySelector('[data-testid="unread-badge"]')).toBeNull();

    // Row 2 badge should still be 1
    const card2 = container.querySelector(
      '[data-testid="conversation-card-2"]',
    );
    expect(
      card2?.querySelector('[data-testid="unread-badge"]')?.textContent,
    ).toContain("1");

    // Header total unread reflects payload.unread_count (1)
    expect(
      container.querySelector('[data-testid="header-unread-count"]')
        ?.textContent,
    ).toContain("1");
  });

  it("filters conversation list by search query", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce(mockConversations);
    await act(async () => {
      root.render(<ConversationList onSelectConversation={vi.fn()} />);
    });

    expect(container.textContent).toContain("Sarah Recruiter");
    expect(container.textContent).toContain("Khalil Kaddoura");

    const searchInput = container.querySelector<HTMLInputElement>(
      '[data-testid="conversation-search"]',
    );
    expect(searchInput).not.toBeNull();

    await act(async () => {
      if (searchInput) {
        setNativeValue(searchInput, "Sarah");
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
        searchInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    expect(container.textContent).toContain("Sarah Recruiter");
    expect(container.textContent).not.toContain("Khalil Kaddoura");
  });

  it("renders empty state when no conversations exist", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce([]);
    await act(async () => {
      root.render(<ConversationList onSelectConversation={vi.fn()} />);
    });

    expect(
      container.querySelector('[data-testid="no-conversations-empty"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("No conversations yet");
  });

  it("displays error state and retries on button click", async () => {
    vi.mocked(api.listConversations)
      .mockRejectedValueOnce(new Error("Network timeout"))
      .mockResolvedValueOnce(mockConversations);

    await act(async () => {
      root.render(<ConversationList onSelectConversation={vi.fn()} />);
    });

    expect(container.textContent).toContain("Failed to load conversations.");

    const retryBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="retry-conversations-btn"]',
    );
    expect(retryBtn).not.toBeNull();

    await act(async () => {
      retryBtn?.click();
    });

    expect(container.textContent).toContain("Sarah Recruiter");
  });
});
