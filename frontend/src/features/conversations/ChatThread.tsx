import React, { useCallback, useEffect, useRef, useState } from "react";
import { useWsEvent, wsClient } from "../../api/ws";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import {
  deleteMessage,
  editMessage,
  getCurrentUserId,
  listMessages,
  markAsRead,
  sendMessage,
} from "./api";
import { MessageBubble } from "./MessageBubble";
import { MessageInput } from "./MessageInput";
import type {
  ConversationItem,
  MessageItem,
  WsMessageDeletedPayload,
  WsMessagePayload,
  WsMessageStatusPayload,
  WsMessageUpdatedPayload,
} from "./types";

export interface ChatThreadProps {
  conversationId: number;
  conversation?: ConversationItem | null;
  currentUserId?: number | null;
  onBack?: () => void;
}

export const ChatThread: React.FC<ChatThreadProps> = ({
  conversationId,
  conversation,
  currentUserId: propUserId,
  onBack,
}) => {
  const { t } = useText();
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prevBeforeId, setPrevBeforeId] = useState<number | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);

  // Authenticated user ID resolution
  const [resolvedUserId, setResolvedUserId] = useState<number | null>(
    () => propUserId ?? getCurrentUserId(),
  );

  useEffect(() => {
    if (propUserId !== undefined) {
      setResolvedUserId(propUserId);
    } else {
      setResolvedUserId(getCurrentUserId());
    }
  }, [propUserId]);

  const peerDisplayName =
    conversation?.peer?.display_name ||
    conversation?.title ||
    (conversation?.type === "ai"
      ? t("chat.assistant")
      : t("chat.directConversation"));

  // Scroll to bottom helper
  const scrollToBottom = useCallback((smooth = false) => {
    const el = containerRef.current;
    if (!el) return;
    if (typeof el.scrollTo === "function") {
      el.scrollTo({
        top: el.scrollHeight,
        behavior: smooth ? "smooth" : "auto",
      });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const threshold = 80;
    isAtBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
  };

  // Initial load of conversation messages
  const loadInitialMessages = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await listMessages(conversationId, null, 50);
      setMessages(res.items);
      setPrevBeforeId(res.prev_before_id);

      // Auto mark read for the latest message
      if (res.items.length > 0) {
        const lastMsg = res.items[res.items.length - 1];
        if (lastMsg.author_id !== resolvedUserId) {
          void Promise.resolve(markAsRead(conversationId, lastMsg.id)).catch(
            () => {},
          );
          wsClient.send("read", {
            conversation_id: conversationId,
            last_message_id: lastMsg.id,
          });
          wsClient.send("delivered", { message_id: lastMsg.id });
        }
      }

      // Initial scroll to bottom after layout
      setTimeout(() => {
        scrollToBottom(false);
      }, 50);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e.message || t("chat.failedToLoadMessages"));
    } finally {
      setLoading(false);
    }
  }, [conversationId, resolvedUserId, scrollToBottom, t]);

  useEffect(() => {
    loadInitialMessages();
  }, [loadInitialMessages]);

  // Load older messages (cursor pagination)
  const handleLoadOlder = async () => {
    if (!prevBeforeId || loadingOlder) return;

    const el = containerRef.current;
    const prevHeight = el ? el.scrollHeight : 0;
    const prevScrollTop = el ? el.scrollTop : 0;

    try {
      setLoadingOlder(true);
      const res = await listMessages(conversationId, prevBeforeId, 50);
      setMessages((prev) => [...res.items, ...prev]);
      setPrevBeforeId(res.prev_before_id);

      // Maintain scroll position so older messages don't jump
      requestAnimationFrame(() => {
        if (el) {
          const newHeight = el.scrollHeight;
          el.scrollTop = newHeight - prevHeight + prevScrollTop;
        }
      });
    } catch {
      // Silently keep current state on paging error
    } finally {
      setLoadingOlder(false);
    }
  };

  // Optimistic Send Message
  const handleSendMessage = async (content: string, idempotencyKey: string) => {
    const tempId = -Date.now();
    const optimisticMessage: MessageItem = {
      id: tempId,
      conversation_id: conversationId,
      author_id: resolvedUserId,
      content,
      status: "sending",
      idempotency_key: idempotencyKey,
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, optimisticMessage]);
    scrollToBottom(true);

    try {
      const res = await sendMessage(conversationId, {
        content,
        idempotency_key: idempotencyKey,
      });

      if (res.items && res.items.length > 0) {
        const confirmedMsg = res.items[0];
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tempId || m.idempotency_key === idempotencyKey
              ? {
                  ...confirmedMsg,
                  status:
                    (confirmedMsg.status as MessageItem["status"]) || "sent",
                }
              : m,
          ),
        );
      }
    } catch {
      // Mark as failed on error
      setMessages((prev) =>
        prev.map((m) =>
          m.id === tempId || m.idempotency_key === idempotencyKey
            ? { ...m, status: "failed" }
            : m,
        ),
      );
    }
  };

  // Retry sending a failed message
  const handleRetry = async (msg: MessageItem) => {
    setMessages((prev) =>
      prev.map((m) => (m.id === msg.id ? { ...m, status: "sending" } : m)),
    );

    try {
      const res = await sendMessage(conversationId, {
        content: msg.content,
        idempotency_key: msg.idempotency_key || undefined,
      });

      if (res.items && res.items.length > 0) {
        const confirmedMsg = res.items[0];
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msg.id
              ? {
                  ...confirmedMsg,
                  status:
                    (confirmedMsg.status as MessageItem["status"]) || "sent",
                }
              : m,
          ),
        );
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) => (m.id === msg.id ? { ...m, status: "failed" } : m)),
      );
    }
  };

  // Edit Message
  const handleEditMessage = async (mid: number, newContent: string) => {
    const updated = await editMessage(conversationId, mid, {
      content: newContent,
    });
    setMessages((prev) =>
      prev.map((m) =>
        m.id === mid
          ? {
              ...m,
              content: updated.content,
              edited_at: updated.edited_at || new Date().toISOString(),
            }
          : m,
      ),
    );
  };

  // Delete Message
  const handleDeleteMessage = async (mid: number) => {
    await deleteMessage(conversationId, mid);
    setMessages((prev) =>
      prev.map((m) =>
        m.id === mid ? { ...m, deleted_at: new Date().toISOString() } : m,
      ),
    );
  };

  // Real-time WebSocket Listeners
  useWsEvent<WsMessagePayload>("message", (payload) => {
    if (!payload || payload.conversation_id !== conversationId) return;

    setMessages((prev) => {
      // Deduplicate by ID or idempotency_key
      const exists = prev.some(
        (m) =>
          m.id === payload.id ||
          (payload.idempotency_key &&
            m.idempotency_key === payload.idempotency_key),
      );
      if (exists) {
        return prev.map((m) =>
          m.id === payload.id ||
          (payload.idempotency_key &&
            m.idempotency_key === payload.idempotency_key)
            ? {
                ...m,
                ...payload,
                status: (payload.status as MessageItem["status"]) || "sent",
              }
            : m,
        );
      }

      const newMsg: MessageItem = {
        ...payload,
        status: (payload.status as MessageItem["status"]) || "sent",
      };
      return [...prev, newMsg];
    });

    // Mark read if incoming from peer
    if (payload.author_id !== resolvedUserId) {
      void Promise.resolve(markAsRead(conversationId, payload.id)).catch(
        () => {},
      );
      wsClient.send("read", {
        conversation_id: conversationId,
        last_message_id: payload.id,
      });
      wsClient.send("delivered", { message_id: payload.id });
    }

    if (isAtBottomRef.current) {
      setTimeout(() => scrollToBottom(true), 50);
    }
  });

  useWsEvent<WsMessageUpdatedPayload>("message_updated", (payload) => {
    if (!payload || payload.conversation_id !== conversationId) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === payload.id
          ? { ...m, content: payload.content, edited_at: payload.edited_at }
          : m,
      ),
    );
  });

  useWsEvent<WsMessageDeletedPayload>("message_deleted", (payload) => {
    if (!payload || payload.conversation_id !== conversationId) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === payload.id
          ? { ...m, deleted_at: new Date().toISOString() }
          : m,
      ),
    );
  });

  useWsEvent<WsMessageStatusPayload>("message_status", (payload) => {
    if (!payload || !payload.message_id) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === payload.message_id
          ? { ...m, status: payload.status as MessageItem["status"] }
          : m,
      ),
    );
  });

  // Date Divider formatting
  const formatDateDivider = (dateStr: string): string => {
    try {
      const d = new Date(dateStr);
      const today = new Date();
      const yesterday = new Date(today);
      yesterday.setDate(yesterday.getDate() - 1);

      if (d.toDateString() === today.toDateString()) return t("chat.today");
      if (d.toDateString() === yesterday.toDateString())
        return t("chat.yesterday");
      return d.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: d.getFullYear() !== today.getFullYear() ? "numeric" : undefined,
      });
    } catch {
      return "";
    }
  };

  return (
    <div
      className="flex h-full flex-col bg-white dark:bg-gray-900"
      data-testid="chat-thread"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-100 p-4 dark:border-gray-800">
        <div className="flex items-center space-x-3">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 md:hidden"
              aria-label={t("chat.backToConversations")}
              data-testid="thread-back-btn"
            >
              <svg
                className="h-5 w-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 19l-7-7 7-7"
                />
              </svg>
            </button>
          )}

          <div className="min-w-0">
            <h2
              className="truncate text-base font-semibold text-gray-900 dark:text-gray-100"
              data-testid="thread-peer-name"
            >
              {peerDisplayName}
            </h2>
            {conversation?.job_title && (
              <p className="truncate text-xs text-primary-600 dark:text-primary-400">
                {t("chat.appliedFor", { job: conversation.job_title })}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Message History Scroll Area */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-4"
        data-testid="message-list-container"
      >
        {loading ? (
          <div
            className="flex h-full items-center justify-center py-12"
            data-testid="thread-loading"
          >
            <Spinner size="md" />
          </div>
        ) : error ? (
          <div
            className="flex h-full flex-col items-center justify-center p-6 text-center"
            data-testid="thread-error"
          >
            <p className="text-sm text-red-500">{error}</p>
            <button
              type="button"
              onClick={loadInitialMessages}
              className="mt-2 text-xs font-semibold text-primary-600 hover:underline"
            >
              {t("chat.retry")}
            </button>
          </div>
        ) : messages.length === 0 ? (
          <div
            className="flex h-full flex-col items-center justify-center p-6 text-center text-gray-400 dark:text-gray-500"
            data-testid="empty-thread-prompt"
          >
            <svg
              className="mb-2 h-8 w-8 text-gray-300 dark:text-gray-600"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
            <p className="text-sm font-medium text-gray-600 dark:text-gray-300">
              {t("chat.noMessagesYetPrompt")}
            </p>
            <p className="mt-1 text-xs text-gray-400">
              {t("chat.startConversationPrompt")}
            </p>
          </div>
        ) : (
          <>
            {/* Load older messages button */}
            {prevBeforeId !== null && (
              <div className="mb-4 flex justify-center">
                <button
                  type="button"
                  onClick={handleLoadOlder}
                  disabled={loadingOlder}
                  className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 shadow-sm hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
                  data-testid="load-older-btn"
                >
                  {loadingOlder
                    ? t("chat.loadingEarlier")
                    : t("chat.loadEarlierMessages")}
                </button>
              </div>
            )}

            {/* Messages list with date dividers */}
            {messages.map((msg, index) => {
              const prevMsg = messages[index - 1];
              const currentDate = new Date(msg.created_at).toDateString();
              const prevDate = prevMsg
                ? new Date(prevMsg.created_at).toDateString()
                : null;
              const showDivider = currentDate !== prevDate;
              const isOwn =
                resolvedUserId !== null && msg.author_id === resolvedUserId;

              return (
                <React.Fragment key={msg.id}>
                  {showDivider && (
                    <div
                      className="my-4 flex items-center justify-center"
                      data-testid="date-divider"
                    >
                      <span className="rounded-full bg-gray-100 px-3 py-0.5 text-[11px] font-medium text-gray-500 shadow-xs dark:bg-gray-800 dark:text-gray-400">
                        {formatDateDivider(msg.created_at)}
                      </span>
                    </div>
                  )}
                  <MessageBubble
                    message={msg}
                    isOwn={isOwn}
                    peerName={!isOwn ? peerDisplayName : undefined}
                    onEdit={handleEditMessage}
                    onDelete={handleDeleteMessage}
                    onRetry={handleRetry}
                  />
                </React.Fragment>
              );
            })}
          </>
        )}
      </div>

      {/* Message Input */}
      <MessageInput
        onSend={handleSendMessage}
        disabled={loading || Boolean(error)}
        placeholder={t("chat.messagePlaceholder", { name: peerDisplayName })}
      />
    </div>
  );
};
