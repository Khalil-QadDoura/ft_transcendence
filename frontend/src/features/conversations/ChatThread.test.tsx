import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { ChatThread } from "./ChatThread";
import type { ConversationItem, MessageItem } from "./types";

// Mock the API module
vi.mock("./api", () => ({
  listMessages: vi.fn(),
  sendMessage: vi.fn(),
  editMessage: vi.fn(),
  deleteMessage: vi.fn(),
  markAsRead: vi.fn(),
  getCurrentUserId: vi.fn(() => 1),
}));

// Mock WebSocket event hook & client
type WsCallback<T> = (payload: T) => void;
const wsListeners = new Map<string, WsCallback<unknown>>();
const mockWsSend = vi.fn();

vi.mock("../../api/ws", () => ({
  useWsEvent: vi.fn((type: string, handler: WsCallback<unknown>) => {
    wsListeners.set(type, handler);
  }),
  wsClient: {
    send: (...args: unknown[]) => mockWsSend(...args),
  },
}));

const mockConversation: ConversationItem = {
  id: 10,
  type: "direct",
  title: null,
  job_id: 42,
  job_title: "Full Stack Developer",
  last_message_id: 102,
  last_message_content: "Sounds great, see you then!",
  last_message_author_id: 2,
  unread_count: 1,
  updated_at: "2026-11-13T10:00:00Z",
  peer: {
    id: 2,
    display_name: "Sarah Recruiter",
    avatar_url: null,
  },
};

const mockMessages: MessageItem[] = [
  {
    id: 100,
    conversation_id: 10,
    author_id: 1, // current user
    content: "Hi Sarah, thanks for reaching out!",
    status: "read",
    message_type: "text",
    reply_to_id: null,
    idempotency_key: "idem-100",
    edited_at: null,
    deleted_at: null,
    created_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(), // 10 mins ago
  },
  {
    id: 101,
    conversation_id: 10,
    author_id: 2, // peer
    content: "Are you available for a chat today?",
    status: "read",
    message_type: "text",
    reply_to_id: null,
    idempotency_key: "idem-101",
    edited_at: null,
    deleted_at: null,
    created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(), // 5 mins ago
  },
];

describe("ChatThread Component (FE-30)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsListeners.clear();
    mockWsSend.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders message history with bubbles, peer header and marks last message as read", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: mockMessages,
      prev_before_id: null,
    });
    vi.mocked(api.markAsRead).mockResolvedValueOnce();

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    // Initial loading indicator
    expect(screen.getByTestId("thread-loading")).toBeInTheDocument();

    await waitFor(() => {
      // Header details
      expect(screen.getByTestId("thread-peer-name")).toHaveTextContent("Sarah Recruiter");
      expect(screen.getByText("Applied for: Full Stack Developer")).toBeInTheDocument();

      // Messages rendered
      expect(screen.getByText("Hi Sarah, thanks for reaching out!")).toBeInTheDocument();
      expect(screen.getByText("Are you available for a chat today?")).toBeInTheDocument();
    });

    // Mark as read was called for incoming message (id: 101)
    expect(api.markAsRead).toHaveBeenCalledWith(10, 101);
    expect(mockWsSend).toHaveBeenCalledWith("read", {
      conversation_id: 10,
      last_message_id: 101,
    });
    expect(mockWsSend).toHaveBeenCalledWith("delivered", { message_id: 101 });
  });

  it("loads older messages when pagination button is clicked", async () => {
    vi.mocked(api.listMessages)
      .mockResolvedValueOnce({
        items: [mockMessages[1]],
        prev_before_id: 100,
      })
      .mockResolvedValueOnce({
        items: [mockMessages[0]],
        prev_before_id: null,
      });

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("load-older-btn")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("load-older-btn"));

    await waitFor(() => {
      expect(api.listMessages).toHaveBeenCalledWith(10, 100, 50);
      expect(screen.getByText("Hi Sarah, thanks for reaching out!")).toBeInTheDocument();
      expect(screen.queryByTestId("load-older-btn")).not.toBeInTheDocument();
    });
  });

  it("optimistically sends a message and resolves with server response", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [],
      prev_before_id: null,
    });

    const sentMessage: MessageItem = {
      id: 200,
      conversation_id: 10,
      author_id: 1,
      content: "Let's schedule a call at 3pm.",
      status: "sent",
      idempotency_key: "key-xyz",
      created_at: new Date().toISOString(),
    };

    vi.mocked(api.sendMessage).mockResolvedValueOnce({
      items: [sentMessage],
    });

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("empty-thread-prompt")).toBeInTheDocument();
    });

    const textarea = screen.getByTestId("message-textarea");
    const sendBtn = screen.getByTestId("send-message-btn");

    fireEvent.change(textarea, { target: { value: "Let's schedule a call at 3pm." } });
    fireEvent.click(sendBtn);

    // Optimistically rendered immediately
    expect(screen.getByText("Let's schedule a call at 3pm.")).toBeInTheDocument();

    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledWith(
        10,
        expect.objectContaining({
          content: "Let's schedule a call at 3pm.",
          idempotency_key: expect.any(String),
        }),
      );
      // Status badge updated to sent (✓)
      expect(screen.getByTestId("msg-status-200")).toHaveTextContent("✓");
    });
  });

  it("shows retry button on send failure and allows retrying", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [],
      prev_before_id: null,
    });

    vi.mocked(api.sendMessage)
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValueOnce({
        items: [
          {
            id: 205,
            conversation_id: 10,
            author_id: 1,
            content: "Retried message content",
            status: "sent",
            created_at: new Date().toISOString(),
          },
        ],
      });

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("message-textarea")).toBeInTheDocument();
    });

    const textarea = screen.getByTestId("message-textarea");
    const sendBtn = screen.getByTestId("send-message-btn");

    fireEvent.change(textarea, { target: { value: "Retried message content" } });
    fireEvent.click(sendBtn);

    // Wait for failure state
    await waitFor(() => {
      expect(screen.getByTitle("Failed to send. Click to retry.")).toBeInTheDocument();
    });

    // Click retry
    const retryBtn = screen.getByTitle("Failed to send. Click to retry.");
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(2);
      expect(screen.getByTestId("msg-status-205")).toHaveTextContent("✓");
    });
  });

  it("edits own message within 15 minutes window", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [mockMessages[0]], // 10 minutes old own message
      prev_before_id: null,
    });

    const updatedMsg: MessageItem = {
      ...mockMessages[0],
      content: "Updated greeting message",
      edited_at: new Date().toISOString(),
    };

    vi.mocked(api.editMessage).mockResolvedValueOnce(updatedMsg);

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Hi Sarah, thanks for reaching out!")).toBeInTheDocument();
    });

    // Click edit button
    const editBtn = screen.getByTestId("edit-msg-btn-100");
    fireEvent.click(editBtn);

    const editInput = screen.getByTestId("edit-msg-input-100");
    fireEvent.change(editInput, { target: { value: "Updated greeting message" } });

    const saveBtn = screen.getByTestId("save-edit-btn-100");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(api.editMessage).toHaveBeenCalledWith(10, 100, {
        content: "Updated greeting message",
      });
      expect(screen.getByText("Updated greeting message")).toBeInTheDocument();
      expect(screen.getByTestId("edited-badge-100")).toHaveTextContent("(edited)");
    });
  });

  it("soft deletes own message with confirmation", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [mockMessages[0]],
      prev_before_id: null,
    });

    vi.mocked(api.deleteMessage).mockResolvedValueOnce();

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Hi Sarah, thanks for reaching out!")).toBeInTheDocument();
    });

    // Click delete trigger
    const deleteBtn = screen.getByTestId("delete-msg-btn-100");
    fireEvent.click(deleteBtn);

    // Confirmation prompt appears
    expect(screen.getByTestId("delete-confirm-prompt-100")).toBeInTheDocument();

    const confirmBtn = screen.getByTestId("confirm-delete-btn-100");
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(api.deleteMessage).toHaveBeenCalledWith(10, 100);
      expect(screen.getByText("This message was deleted")).toBeInTheDocument();
    });
  });

  it("handles live WebSocket message, message_updated and message_deleted events", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [mockMessages[0]],
      prev_before_id: null,
    });

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Hi Sarah, thanks for reaching out!")).toBeInTheDocument();
    });

    // 1. Incoming live message from peer
    const messageHandler = wsListeners.get("message");
    expect(messageHandler).toBeDefined();

    messageHandler?.({
      id: 300,
      conversation_id: 10,
      author_id: 2,
      content: "Let's speak in 10 minutes.",
      status: "sent",
      created_at: new Date().toISOString(),
    });

    await waitFor(() => {
      expect(screen.getByText("Let's speak in 10 minutes.")).toBeInTheDocument();
    });

    // 2. Incoming message_updated event
    const updateHandler = wsListeners.get("message_updated");
    expect(updateHandler).toBeDefined();

    updateHandler?.({
      id: 300,
      conversation_id: 10,
      author_id: 2,
      content: "Let's speak in 20 minutes instead.",
      edited_at: new Date().toISOString(),
    });

    await waitFor(() => {
      expect(screen.getByText("Let's speak in 20 minutes instead.")).toBeInTheDocument();
    });

    // 3. Incoming message_deleted event
    const deleteHandler = wsListeners.get("message_deleted");
    expect(deleteHandler).toBeDefined();

    deleteHandler?.({
      id: 300,
      conversation_id: 10,
    });

    await waitFor(() => {
      expect(screen.getByText("This message was deleted")).toBeInTheDocument();
    });
  });

  it("updates message delivery status live via message_status event", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [
        {
          id: 100,
          conversation_id: 10,
          author_id: 1,
          content: "Hello",
          status: "sent",
          created_at: new Date().toISOString(),
        },
      ],
      prev_before_id: null,
    });

    render(
      <ChatThread
        conversationId={10}
        conversation={mockConversation}
        currentUserId={1}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("msg-status-100")).toHaveTextContent("✓");
    });

    // Receive message_status delivered event
    const statusHandler = wsListeners.get("message_status");
    statusHandler?.({
      message_id: 100,
      status: "delivered",
    });

    await waitFor(() => {
      expect(screen.getByTestId("msg-status-100")).toHaveTextContent("✓✓");
    });

    // Receive message_status read event
    statusHandler?.({
      message_id: 100,
      status: "read",
    });

    await waitFor(() => {
      expect(screen.getByTestId("msg-status-100")).toHaveTextContent("✓✓");
    });
  });
});
