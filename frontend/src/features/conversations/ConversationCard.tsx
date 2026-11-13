import React from "react";
import { Avatar } from "../../components/Avatar";
import { Badge } from "../../components/Badge";
import { useText } from "../../i18n/useText";
import type { ConversationItem } from "./types";

export interface ConversationCardProps {
  conversation: ConversationItem;
  isSelected?: boolean;
  onClick: (conversation: ConversationItem) => void;
}

export const ConversationCard: React.FC<ConversationCardProps> = ({
  conversation,
  isSelected = false,
  onClick,
}) => {
  const { t } = useText();
  const displayName =
    conversation.peer?.display_name ||
    conversation.title ||
    (conversation.type === "ai"
      ? t("chat.assistant")
      : t("chat.directConversation"));

  const avatarUrl = conversation.peer?.avatar_url || undefined;

  const formatTimestamp = (dateStr?: string) => {
    if (!dateStr) return "";
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / (1000 * 60));
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

      if (diffMins < 1) return t("chat.justNow");
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      return date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      });
    } catch {
      return "";
    }
  };

  return (
    <button
      type="button"
      onClick={() => onClick(conversation)}
      className={`group flex w-full items-start space-x-3.5 rounded-xl p-3.5 text-left transition-all duration-150 ${
        isSelected
          ? "bg-primary-50/80 ring-1 ring-primary-500/30 dark:bg-primary-950/40 dark:ring-primary-400/30"
          : "hover:bg-gray-100/70 dark:hover:bg-gray-800/60"
      }`}
      data-testid={`conversation-card-${conversation.id}`}
    >
      <div className="relative shrink-0">
        <Avatar src={avatarUrl} name={displayName} size="md" />
        {conversation.unread_count > 0 && (
          <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-400 opacity-75"></span>
            <span
              className="relative inline-flex h-2.5 w-2.5 rounded-full bg-primary-600"
              data-testid="unread-badge"
            >
              <span className="sr-only">{conversation.unread_count}</span>
            </span>
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2 truncate">
            <span
              className={`truncate text-sm font-semibold ${
                conversation.unread_count > 0
                  ? "text-gray-900 dark:text-gray-50"
                  : "text-gray-800 dark:text-gray-200"
              }`}
              data-testid="conversation-name"
            >
              {displayName}
            </span>
            {conversation.job_title && (
              <Badge
                variant="neutral"
                size="sm"
                className="hidden sm:inline-flex"
              >
                {conversation.job_title}
              </Badge>
            )}
          </div>
          <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500">
            {formatTimestamp(conversation.updated_at)}
          </span>
        </div>

        <div className="mt-1 flex items-center justify-between">
          <p
            className={`truncate text-xs ${
              conversation.unread_count > 0
                ? "font-medium text-gray-900 dark:text-gray-100"
                : "text-gray-500 dark:text-gray-400"
            }`}
            data-testid="conversation-snippet"
          >
            {conversation.last_message_content || t("chat.noMessagesYet")}
          </p>
        </div>
      </div>
    </button>
  );
};
