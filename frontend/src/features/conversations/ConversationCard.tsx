import { activeLanguage, formatNumber, formatDate } from "../../i18n";
import { relativePast } from "../../i18n/date-format";
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
      if (diffMins < 60)
        return relativePast(diffMins, "minute", activeLanguage());
      if (diffHours < 24)
        return relativePast(diffHours, "hour", activeLanguage());
      return formatDate(date, {
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
      className={`group flex w-full items-start gap-3.5 rounded-xl p-3.5 text-start transition-all duration-150 ${
        isSelected
          ? "bg-surface-muted ring-1 ring-border shadow-xs"
          : "hover:bg-surface-muted/60"
      }`}
      data-testid={`conversation-card-${conversation.id}`}
    >
      <div className="relative shrink-0">
        <Avatar src={avatarUrl} alt={displayName} size="md" />
        {conversation.unread_count > 0 && (
          <span
            className="absolute -top-1.5 -end-1.5 inline-flex items-center justify-center min-w-5 h-5 px-1 text-[11px] font-bold rounded-full bg-lime text-ink border border-surface shadow-xs"
            data-testid="unread-badge"
          >
            {formatNumber(conversation.unread_count)}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 truncate">
            <span
              className={`truncate text-sm font-semibold ${
                conversation.unread_count > 0
                  ? "text-ink font-bold"
                  : "text-ink"
              }`}
              data-testid="conversation-name"
            >
              <bdi>{displayName}</bdi>
            </span>
            {conversation.job_title && (
              <Badge
                variant="outline"
                size="sm"
                className="hidden sm:inline-flex"
              >
                <bdi>{conversation.job_title}</bdi>
              </Badge>
            )}
          </div>
          <span className="shrink-0 text-xs text-ink-muted">
            {formatTimestamp(conversation.updated_at)}
          </span>
        </div>

        <div className="mt-1 flex items-center justify-between">
          <p
            dir="auto"
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
