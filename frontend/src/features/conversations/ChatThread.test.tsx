import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
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

let root: Root;
let container: HTMLDivElement;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function setNativeValue(
  element: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const prototypeValueSetter = Object.getOwnPropertyDescriptor(
    prototype,
    "value",
  )?.set;

  if (prototypeValueSetter) {
    prototypeValueSetter.call(element, value);
  } else {
    element.value = value;
  }

  const tracker = (
    element as unknown as {
      _valueTracker?: { setValue: (v: string) => void };
    }
  )._valueTracker;
  if (tracker) {
    tracker.setValue("");
  }
}

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
    created_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
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
    created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  },
];

describe("ChatThread Component (FE-30)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.listMessages).mockResolvedValue({
      items: [],
      prev_before_id: null,
    });
    vi.mocked(api.sendMessage).mockResolvedValue({ items: [] });
    vi.mocked(api.editMessage).mockResolvedValue({ ...mockMessages[0] });
    vi.mocked(api.deleteMessage).mockResolvedValue(undefined);
    vi.mocked(api.markAsRead).mockResolvedValue(undefined);
    vi.mocked(api.getCurrentUserId).mockReturnValue(1);
    wsListeners.clear();
    mockWsSend.mockClear();
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

  it("renders message history with bubbles, peer header and marks last message as read", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: mockMessages,
      prev_before_id: null,
    });
    vi.mocked(api.markAsRead).mockResolvedValueOnce();

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    expect(
      container.querySelector('[data-testid="thread-peer-name"]')?.textContent,
    ).toContain("Sarah Recruiter");
    expect(container.textContent).toContain(
      "Applied for: Full Stack Developer",
    );
    expect(container.textContent).toContain(
      "Hi Sarah, thanks for reaching out!",
    );
    expect(container.textContent).toContain(
      "Are you available for a chat today?",
    );

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

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    const loadOlderBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="load-older-btn"]',
    );
    expect(loadOlderBtn).not.toBeNull();

    await act(async () => {
      loadOlderBtn?.click();
    });

    expect(api.listMessages).toHaveBeenCalledWith(10, 100, 50);
    expect(container.textContent).toContain(
      "Hi Sarah, thanks for reaching out!",
    );
    expect(
      container.querySelector('[data-testid="load-older-btn"]'),
    ).toBeNull();
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

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    const textarea = container.querySelector<HTMLTextAreaElement>(
      '[data-testid="message-textarea"]',
    );
    const sendBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="send-message-btn"]',
    );
    expect(textarea).not.toBeNull();
    expect(sendBtn).not.toBeNull();

    await act(async () => {
      if (textarea) {
        setNativeValue(textarea, "Let's schedule a call at 3pm.");
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        textarea.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    await act(async () => {
      sendBtn?.click();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Let's schedule a call at 3pm.");
    expect(api.sendMessage).toHaveBeenCalledWith(
      10,
      expect.objectContaining({
        content: "Let's schedule a call at 3pm.",
        idempotency_key: expect.any(String),
      }),
    );
    expect(
      container.querySelector('[data-testid="msg-status-200"]')?.textContent,
    ).toContain("✓");
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

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    const textarea = container.querySelector<HTMLTextAreaElement>(
      '[data-testid="message-textarea"]',
    );
    const sendBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="send-message-btn"]',
    );

    await act(async () => {
      if (textarea) {
        setNativeValue(textarea, "Retried message content");
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        textarea.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    await act(async () => {
      sendBtn?.click();
      await Promise.resolve();
    });

    const retryBtn = container.querySelector<HTMLButtonElement>(
      '[title="Failed to send. Click to retry."]',
    );
    expect(retryBtn).not.toBeNull();

    await act(async () => {
      retryBtn?.click();
      await Promise.resolve();
    });

    expect(api.sendMessage).toHaveBeenCalledTimes(2);
    expect(
      container.querySelector('[data-testid="msg-status-205"]')?.textContent,
    ).toContain("✓");
  });

  it("edits own message within 15 minutes window", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [mockMessages[0]],
      prev_before_id: null,
    });

    const updatedMsg: MessageItem = {
      ...mockMessages[0],
      content: "Updated greeting message",
      edited_at: new Date().toISOString(),
    };

    vi.mocked(api.editMessage).mockResolvedValueOnce(updatedMsg);

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain(
      "Hi Sarah, thanks for reaching out!",
    );

    const editBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="edit-msg-btn-100"]',
    );
    expect(editBtn).not.toBeNull();

    await act(async () => {
      editBtn?.click();
    });

    const editInput = container.querySelector<HTMLInputElement>(
      '[data-testid="edit-msg-input-100"]',
    );
    expect(editInput).not.toBeNull();

    await act(async () => {
      if (editInput) {
        setNativeValue(editInput, "Updated greeting message");
        editInput.dispatchEvent(new Event("input", { bubbles: true }));
        editInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });

    const saveBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="save-edit-btn-100"]',
    );
    expect(saveBtn).not.toBeNull();

    await act(async () => {
      saveBtn?.click();
      await Promise.resolve();
    });

    expect(api.editMessage).toHaveBeenCalledWith(10, 100, {
      content: "Updated greeting message",
    });
    expect(container.textContent).toContain("Updated greeting message");
    expect(
      container.querySelector('[data-testid="edited-badge-100"]')?.textContent,
    ).toContain("(edited)");
  });

  it("soft deletes own message with confirmation", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [mockMessages[0]],
      prev_before_id: null,
    });

    vi.mocked(api.deleteMessage).mockResolvedValueOnce();

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain(
      "Hi Sarah, thanks for reaching out!",
    );

    const deleteBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="delete-msg-btn-100"]',
    );
    expect(deleteBtn).not.toBeNull();

    await act(async () => {
      deleteBtn?.click();
    });

    expect(
      container.querySelector('[data-testid="delete-confirm-prompt-100"]'),
    ).not.toBeNull();

    const confirmBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="confirm-delete-btn-100"]',
    );
    expect(confirmBtn).not.toBeNull();

    await act(async () => {
      confirmBtn?.click();
      await Promise.resolve();
    });

    expect(api.deleteMessage).toHaveBeenCalledWith(10, 100);
    expect(container.textContent).toContain("This message was deleted");
  });

  it("handles live WebSocket message, message_updated and message_deleted events", async () => {
    vi.mocked(api.listMessages).mockResolvedValueOnce({
      items: [mockMessages[0]],
      prev_before_id: null,
    });

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain(
      "Hi Sarah, thanks for reaching out!",
    );

    const messageHandler = wsListeners.get("message");
    expect(messageHandler).toBeDefined();

    await act(async () => {
      messageHandler?.({
        id: 300,
        conversation_id: 10,
        author_id: 2,
        content: "Let's speak in 10 minutes.",
        status: "sent",
        created_at: new Date().toISOString(),
      });
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Let's speak in 10 minutes.");

    const updateHandler = wsListeners.get("message_updated");
    expect(updateHandler).toBeDefined();

    await act(async () => {
      updateHandler?.({
        id: 300,
        conversation_id: 10,
        author_id: 2,
        content: "Let's speak in 20 minutes instead.",
        edited_at: new Date().toISOString(),
      });
    });

    expect(container.textContent).toContain(
      "Let's speak in 20 minutes instead.",
    );

    const deleteHandler = wsListeners.get("message_deleted");
    expect(deleteHandler).toBeDefined();

    await act(async () => {
      deleteHandler?.({
        id: 300,
        conversation_id: 10,
      });
    });

    expect(container.textContent).toContain("This message was deleted");
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

    await act(async () => {
      root.render(
        <ChatThread
          conversationId={10}
          conversation={mockConversation}
          currentUserId={1}
        />,
      );
      await Promise.resolve();
    });

    expect(
      container.querySelector('[data-testid="msg-status-100"]')?.textContent,
    ).toContain("✓");

    const statusHandler = wsListeners.get("message_status");
    await act(async () => {
      statusHandler?.({
        message_id: 100,
        status: "delivered",
      });
    });

    expect(
      container.querySelector('[data-testid="msg-status-100"]')?.textContent,
    ).toContain("✓✓");

    await act(async () => {
      statusHandler?.({
        message_id: 100,
        status: "read",
      });
    });

    expect(
      container.querySelector('[data-testid="msg-status-100"]')?.textContent,
    ).toContain("✓✓");
  });
});
