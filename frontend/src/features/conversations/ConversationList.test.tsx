import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { ConversationList } from "./ConversationList";
import type { ConversationItem, WsConversationUpdatedPayload, WsMessagePayload } from "./types";

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
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders conversations with participant names, avatars, snippets and unread badges", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce(mockConversations);
    const mockOnSelect = vi.fn();

    render(<ConversationList onSelectConversation={mockOnSelect} />);

    // Shows loading spinner first
    expect(screen.getByTestId("conversation-loading")).toBeInTheDocument();

    await waitFor(() => {
      // First conversation details
      expect(screen.getByText("Sarah Recruiter")).toBeInTheDocument();
      expect(screen.getByText("Looking forward to meeting you!")).toBeInTheDocument();
      expect(screen.getByText("Senior Frontend Engineer")).toBeInTheDocument();
      expect(screen.getByTestId("unread-badge")).toHaveTextContent("2");

      // Second conversation details (unread count 0 -> no unread badge)
      expect(screen.getByText("Khalil Kaddoura")).toBeInTheDocument();
      expect(screen.getByText("Did you check the pull request?")).toBeInTheDocument();
    });
  });

  it("handles clicking a conversation and invokes onSelectConversation", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce(mockConversations);
    const mockOnSelect = vi.fn();

    render(<ConversationList onSelectConversation={mockOnSelect} />);

    await waitFor(() => {
      expect(screen.getByText("Sarah Recruiter")).toBeInTheDocument();
    });

    const card = screen.getByTestId("conversation-card-1");
    fireEvent.click(card);

    expect(mockOnSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, last_message_content: "Looking forward to meeting you!" }),
    );
  });

  it("updates snippet, increments unread count, and bumps conversation to top on WebSocket message", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce([...mockConversations]);
    const mockOnSelect = vi.fn();

    render(<ConversationList onSelectConversation={mockOnSelect} />);

    await waitFor(() => {
      expect(screen.getByText("Khalil Kaddoura")).toBeInTheDocument();
    });

    // Simulate real-time message arriving for conversation 2 (currently at index 1)
    const messageHandler = wsListeners.get("message") as WsCallback<WsMessagePayload> | undefined;
    expect(messageHandler).toBeDefined();

    messageHandler?.({
      id: 200,
      conversation_id: 2,
      author_id: 3,
      content: "Let's review the WebSocket client together!",
      created_at: "2026-11-12T11:00:00Z",
    });

    await waitFor(() => {
      // The updated message snippet must be displayed
      expect(screen.getByText("Let's review the WebSocket client together!")).toBeInTheDocument();

      // Check card order in DOM: conversation 2 should now be first!
      const cards = screen.getAllByTestId(/^conversation-card-/);
      expect(cards[0]).toHaveAttribute("data-testid", "conversation-card-2");
      expect(cards[1]).toHaveAttribute("data-testid", "conversation-card-1");
    });
  });

  it("updates unread count when conversation_updated event is received", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce([...mockConversations]);
    const mockOnSelect = vi.fn();

    render(<ConversationList onSelectConversation={mockOnSelect} />);

    await waitFor(() => {
      expect(screen.getByTestId("unread-badge")).toHaveTextContent("2");
    });

    const updateHandler = wsListeners.get("conversation_updated") as
      | WsCallback<WsConversationUpdatedPayload>
      | undefined;
    expect(updateHandler).toBeDefined();

    updateHandler?.({
      conversation_id: 1,
      unread_count: 0,
    });

    await waitFor(() => {
      expect(screen.queryByTestId("unread-badge")).not.toBeInTheDocument();
    });
  });

  it("filters conversation list by search query", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce(mockConversations);
    render(<ConversationList onSelectConversation={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Sarah Recruiter")).toBeInTheDocument();
      expect(screen.getByText("Khalil Kaddoura")).toBeInTheDocument();
    });

    const searchInput = screen.getByTestId("conversation-search");
    fireEvent.change(searchInput, { target: { value: "Sarah" } });

    expect(screen.getByText("Sarah Recruiter")).toBeInTheDocument();
    expect(screen.queryByText("Khalil Kaddoura")).not.toBeInTheDocument();
  });

  it("renders empty state when no conversations exist", async () => {
    vi.mocked(api.listConversations).mockResolvedValueOnce([]);
    render(<ConversationList onSelectConversation={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("no-conversations-empty")).toBeInTheDocument();
      expect(screen.getByText("No conversations yet")).toBeInTheDocument();
    });
  });

  it("displays error state and retries on button click", async () => {
    vi.mocked(api.listConversations)
      .mockRejectedValueOnce(new Error("Network timeout"))
      .mockResolvedValueOnce(mockConversations);

    render(<ConversationList onSelectConversation={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Network timeout")).toBeInTheDocument();
    });

    const retryBtn = screen.getByTestId("retry-conversations-btn");
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText("Sarah Recruiter")).toBeInTheDocument();
    });
  });
});
