import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useWsEvent } from "../../api/ws";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Input } from "../../components/Input";
import { Spinner } from "../../components/Spinner";
import { getConversation, listConversations } from "./api";
import { ConversationCard } from "./ConversationCard";
import type {
  ConversationItem,
  WsConversationUpdatedPayload,
  WsMessagePayload,
} from "./types";

export interface ConversationListProps {
  selectedId?: number | null;
  onSelectConversation: (conv: ConversationItem) => void;
  className?: string;
}

export const ConversationList: React.FC<ConversationListProps> = ({
  selectedId,
  onSelectConversation,
  className = "",
}) => {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");

  const loadConversations = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listConversations();
      setConversations(data);
    } catch (err: unknown) {
      const error = err as { message?: string };
      setError(error.message || "Failed to load conversations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  /**
   * Real-time WebSocket listener: Incoming message bumps conversation to top,
   * updates snippet and increments unread count.
   */
  useWsEvent<WsMessagePayload>("message", (payload) => {
    if (!payload || !payload.conversation_id) return;

    setConversations((prevList) => {
      const index = prevList.findIndex((c) => c.id === payload.conversation_id);

      if (index >= 0) {
        const target = prevList[index];
        const isCurrentlyOpen = selectedId === payload.conversation_id;

        const updatedTarget: ConversationItem = {
          ...target,
          last_message_content: payload.content,
          last_message_id: payload.id,
          last_message_author_id: payload.author_id,
          updated_at: payload.created_at || new Date().toISOString(),
          unread_count: isCurrentlyOpen
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
            return [{ ...newConv, last_message_content: payload.content }, ...current];
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
   */
  useWsEvent<WsConversationUpdatedPayload>("conversation_updated", (payload) => {
    if (!payload || !payload.conversation_id) return;

    setConversations((prevList) => {
      return prevList.map((conv) => {
        if (conv.id === payload.conversation_id) {
          return {
            ...conv,
            unread_count:
              typeof payload.unread_count === "number"
                ? payload.unread_count
                : conv.unread_count,
          };
        }
        return conv;
      });
    });
  });

  // Filter conversations by participant name or job title
  const filteredConversations = useMemo(() => {
    if (!searchQuery.trim()) return conversations;
    const query = searchQuery.toLowerCase();
    return conversations.filter((c) => {
      const name = c.peer?.display_name || c.title || "";
      const job = c.job_title || "";
      return name.toLowerCase().includes(query) || job.toLowerCase().includes(query);
    });
  }, [conversations, searchQuery]);

  return (
    <div
      className={`flex h-full flex-col bg-white dark:bg-gray-900 ${className}`}
      data-testid="conversation-list"
    >
      <div className="border-b border-gray-100 p-4 dark:border-gray-800">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xl font-bold tracking-tight text-gray-900 dark:text-gray-100">
            Messages
          </h2>
          {conversations.some((c) => c.unread_count > 0) && (
            <span className="rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-semibold text-primary-800 dark:bg-primary-950/60 dark:text-primary-300">
              {conversations.reduce((acc, c) => acc + (c.unread_count || 0), 0)} unread
            </span>
          )}
        </div>

        <Input
          type="search"
          placeholder="Search conversations..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="Search conversations"
          data-testid="conversation-search"
        />
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <div className="flex h-48 items-center justify-center" data-testid="conversation-loading">
            <Spinner size="md" />
          </div>
        ) : error ? (
          <div className="p-4 text-center">
            <p className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>
            <Button
              onClick={loadConversations}
              variant="secondary"
              size="sm"
              data-testid="retry-conversations-btn"
            >
              Try Again
            </Button>
          </div>
        ) : filteredConversations.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title={searchQuery ? "No matches found" : "No conversations yet"}
              description={
                searchQuery
                  ? "Try searching for a different name or job title."
                  : "When employers or candidates contact you, your messages will appear here."
              }
              data-testid="no-conversations-empty"
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
