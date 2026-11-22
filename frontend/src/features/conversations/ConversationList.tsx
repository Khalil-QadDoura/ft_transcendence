import { localizeMessage } from "../../i18n/copy";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useWsEvent } from "../../api/ws";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Input } from "../../components/Input";
import { Spinner } from "../../components/Spinner";
import { useText } from "../../i18n/useText";
import { getConversation, listConversations } from "./api";
import { ConversationCard } from "./ConversationCard";
import type {
  ConversationItem,
  WsConversationUpdatedPayload,
  WsMessagePayload,
} from "./types";

export interface ConversationListProps {
  currentUserId?: number;
  selectedId?: number | null;
  onSelectConversation: (conv: ConversationItem) => void;
  className?: string;
}

export const ConversationList: React.FC<ConversationListProps> = ({
  currentUserId,
  selectedId,
  onSelectConversation,
  className = "",
}) => {
  const { t } = useText();
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [totalUnread, setTotalUnread] = useState<number | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");

  const loadConversations = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listConversations();
      setConversations(data);
      setTotalUnread(null);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e.message || t("chat.failedToLoad"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  /**
   * Real-time WebSocket listener: Incoming message bumps conversation to top,
   * updates snippet and increments unread count.
   */
  useWsEvent<WsMessagePayload>("message", (payload) => {
    if (!payload || !payload.conversation_id) return;

    const isMyMessage = Boolean(
      currentUserId && payload.author_id === currentUserId,
    );
    const isCurrentlyOpen = selectedId === payload.conversation_id;

    if (!isMyMessage && !isCurrentlyOpen) {
      setTotalUnread((prev) => (prev !== null ? prev + 1 : null));
    }

    setConversations((prevList) => {
      const index = prevList.findIndex((c) => c.id === payload.conversation_id);

      if (index >= 0) {
        const target = prevList[index];

        const updatedTarget: ConversationItem = {
          ...target,
          last_message_content: payload.content,
          last_message_id: payload.id,
          last_message_author_id: payload.author_id,
          updated_at: payload.created_at || new Date().toISOString(),
          unread_count:
            isCurrentlyOpen || isMyMessage
              ? target.unread_count
              : (target.unread_count || 0) + 1,
        };

        // Bump updated conversation to the top
        const remaining = prevList.filter((_, idx) => idx !== index);
        return [updatedTarget, ...remaining];
      }

      // If conversation is not in current loaded list, fetch and prepend it
      getConversation(payload.conversation_id)
        .then((newConv) => {
          setConversations((current) => {
            if (current.some((c) => c.id === newConv.id)) return current;
            return [
              { ...newConv, last_message_content: payload.content },
              ...current,
            ];
          });
        })
        .catch(() => {
          // Ignore background fetch failure
        });

      return prevList;
    });
  });

  /**
   * Real-time WebSocket listener: Unread count reset or conversation metadata update.
   * When unread_count is a number, it represents the user's total unread count across all conversations
   * after reading conversation_id. We reset this specific row to 0, and use payload.unread_count for the header.
   */
  useWsEvent<WsConversationUpdatedPayload>(
    "conversation_updated",
    (payload) => {
      if (!payload || !payload.conversation_id) return;

      if (typeof payload.unread_count === "number") {
        setTotalUnread(payload.unread_count);
        setConversations((prevList) =>
          prevList.map((conv) =>
            conv.id === payload.conversation_id
              ? { ...conv, unread_count: 0 }
              : conv,
          ),
        );
      }
    },
  );

  // Filter conversations by participant name or job title
  const filteredConversations = useMemo(() => {
    if (!searchQuery.trim()) return conversations;
    const query = searchQuery.toLowerCase();
    return conversations.filter((c) => {
      const name = c.peer?.display_name || c.title || "";
      const job = c.job_title || "";
      return (
        name.toLowerCase().includes(query) || job.toLowerCase().includes(query)
      );
    });
  }, [conversations, searchQuery]);

  const totalUnreadCount =
    totalUnread !== null
      ? totalUnread
      : conversations.reduce((acc, c) => acc + (c.unread_count || 0), 0);

  return (
    <div
      className={`flex h-full flex-col bg-surface text-ink ${className}`}
      data-testid="conversation-list"
    >
      <div className="border-b border-border p-4">
        <div className="mb-3 flex items-center justify-between">
          <h1 className="text-xl font-bold tracking-tight text-ink">
            {t("chat.messages")}
          </h1>
          {totalUnreadCount > 0 && (
            <span
              className="rounded-full bg-lime text-ink px-2.5 py-0.5 text-xs font-semibold"
              data-testid="header-unread-count"
            >
              {t("chat.unreadCount", { count: totalUnreadCount })}
            </span>
          )}
        </div>

        <Input
          type="search"
          placeholder={t("chat.searchPlaceholder")}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label={t("chat.searchAria")}
          data-testid="conversation-search"
        />
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <div
            className="flex h-48 items-center justify-center"
            data-testid="conversation-loading"
          >
            <Spinner size="md" />
          </div>
        ) : error ? (
          <div className="p-4 text-center">
            <p className="mb-3 text-sm text-red-600 dark:text-red-400">
              {localizeMessage(
                "screens",
                error ?? undefined,
                "chat.failedToLoad",
              )}
            </p>
            <Button
              onClick={loadConversations}
              variant="secondary"
              size="sm"
              data-testid="retry-conversations-btn"
            >
              {t("chat.tryAgain")}
            </Button>
          </div>
        ) : filteredConversations.length === 0 ? (
          <div className="p-4" data-testid="no-conversations-empty">
            <EmptyState
              title={
                searchQuery
                  ? t("chat.noMatchesFound")
                  : t("chat.noConversationsYet")
              }
              description={
                searchQuery
                  ? t("chat.noMatchesDesc")
                  : t("chat.noConversationsDesc")
              }
            />
          </div>
        ) : (
          <div className="space-y-1" data-testid="conversations-container">
            {filteredConversations.map((conv) => (
              <ConversationCard
                key={conv.id}
                conversation={conv}
                isSelected={selectedId === conv.id}
                onClick={onSelectConversation}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
