import React from "react";
import { Avatar } from "../../components/Avatar";
import { Badge } from "../../components/Badge";
import { useText } from "../../i18n/useText";
import { useUserPresence } from "../presence";
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
  const isPeerOnline = useUserPresence(conversation.peer?.id);

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
          ? "bg-surface-muted ring-1 ring-border shadow-xs"
          : "hover:bg-surface-muted/60"
      }`}
      data-testid={`conversation-card-${conversation.id}`}
    >
      <div className="relative shrink-0">
        <Avatar src={avatarUrl} alt={displayName} size="md" />
        {conversation.peer && (
          <span
            className={`absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-surface ${
              isPeerOnline ? "bg-emerald-500" : "bg-gray-400"
            }`}
            aria-label={t(
              isPeerOnline ? "controls.online" : "controls.offline",
            )}
            data-testid={`presence-dot-${conversation.peer.id}`}
          />
        )}
        {conversation.unread_count > 0 && (
          <span
            className="absolute -top-1.5 -right-1.5 inline-flex items-center justify-center min-w-5 h-5 px-1 text-[11px] font-bold rounded-full bg-lime text-ink border border-surface shadow-xs"
            data-testid="unread-badge"
          >
            {conversation.unread_count}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2 truncate">
            <span
              className={`truncate text-sm font-semibold ${
                conversation.unread_count > 0
                  ? "text-ink font-bold"
                  : "text-ink"
              }`}
              data-testid="conversation-name"
            >
              {displayName}
            </span>
            {conversation.job_title && (
              <Badge
                variant="outline"
                size="sm"
                className="hidden sm:inline-flex"
              >
                {conversation.job_title}
              </Badge>
            )}
          </div>
          <span className="shrink-0 text-xs text-ink-muted">
            {formatTimestamp(conversation.updated_at)}
          </span>
        </div>

        <div className="mt-1 flex items-center justify-between">
          <p
            className={`truncate text-xs ${
              conversation.unread_count > 0
                ? "font-medium text-ink"
                : "text-ink-muted"
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
