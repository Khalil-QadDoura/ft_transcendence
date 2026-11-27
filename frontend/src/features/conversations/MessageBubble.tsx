import { localizeMessage } from "../../i18n/copy";
import { activeLanguage } from "../../i18n";
import React, { useState } from "react";
import { useText } from "../../i18n/useText";
import type { MessageItem } from "./types";

export interface MessageBubbleProps {
  message: MessageItem;
  isOwn: boolean;
  peerName?: string;
  onEdit?: (messageId: number, content: string) => Promise<void>;
  onDelete?: (messageId: number) => Promise<void>;
  onRetry?: (message: MessageItem) => void;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  message,
  isOwn,
  peerName,
  onEdit,
  onDelete,
  onRetry,
}) => {
  const { t } = useText();
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const isDeleted = Boolean(message.deleted_at);

  // Check 15-minute edit window
  const canEdit = React.useMemo(() => {
    if (
      !isOwn ||
      isDeleted ||
      message.status === "sending" ||
      message.status === "failed"
    ) {
      return false;
    }
    const createdTime = new Date(message.created_at).getTime();
    if (isNaN(createdTime)) return false;
    const fifteenMinutesMs = 15 * 60 * 1000;
    return Date.now() - createdTime <= fifteenMinutesMs;
  }, [isOwn, isDeleted, message.status, message.created_at]);

  const formatTime = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleTimeString(activeLanguage(), {
        hour: "numeric",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  };

  const handleSaveEdit = async () => {
    if (!onEdit || !editContent.trim() || editContent === message.content) {
      setIsEditing(false);
      return;
    }
    try {
      setSavingEdit(true);
      setEditError(null);
      await onEdit(message.id, editContent.trim());
      setIsEditing(false);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setEditError(e.message || t("chat.failedToEdit"));
    } finally {
      setSavingEdit(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    try {
      setDeleting(true);
      await onDelete(message.id);
      setConfirmDelete(false);
    } catch {
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div
      className={`group relative mb-3 flex flex-col ${
        isOwn ? "items-end" : "items-start"
      }`}
      data-testid={`message-bubble-${message.id}`}
      data-author={isOwn ? "self" : "peer"}
    >
      {!isOwn && peerName && (
        <span className="mb-1 text-xs font-medium text-gray-500 dark:text-gray-400">
          {peerName}
        </span>
      )}

      <div className="relative flex max-w-[85%] items-end gap-2 sm:max-w-[70%]">
        {/* Action toolbar for own message (hover) */}
        {isOwn && !isDeleted && !isEditing && (
          <div className="mb-1 hidden items-center gap-1 opacity-0 transition-opacity duration-150 group-hover:opacity-100 sm:flex">
            {canEdit && (
              <button
                type="button"
                onClick={() => {
                  setEditContent(message.content);
                  setIsEditing(true);
                }}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                title={t("chat.editMessageTitle")}
                aria-label={t("chat.editMessageAria")}
                data-testid={`edit-msg-btn-${message.id}`}
              >
                <svg
                  className="h-3.5 w-3.5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                  />
                </svg>
              </button>
            )}
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/40 dark:hover:text-red-400"
              title={t("chat.deleteMessageTitle")}
              aria-label={t("chat.deleteMessageAria")}
              data-testid={`delete-msg-btn-${message.id}`}
            >
              <svg
                className="h-3.5 w-3.5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                />
              </svg>
            </button>
          </div>
        )}

        {/* Bubble container */}
        <div
          className={`relative rounded-2xl px-4 py-2.5 shadow-sm transition-colors ${
            isOwn
              ? isDeleted
                ? "border border-border bg-paper text-ink-muted italic"
                : "bg-ink text-paper"
              : isDeleted
                ? "border border-border bg-paper text-ink-muted italic"
                : "bg-paper-subtle text-ink border border-border-subtle"
          }`}
        >
          {isDeleted ? (
            <div className="flex items-center gap-1.5 py-0.5">
              <svg
                className="h-4 w-4 shrink-0 text-gray-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
                />
              </svg>
              <span className="text-sm">{t("chat.messageDeleted")}</span>
            </div>
          ) : isEditing ? (
            <div className="flex min-w-[220px] flex-col space-y-2 py-1">
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                maxLength={4000}
                rows={2}
                className="w-full resize-none rounded-lg border border-border bg-surface p-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-lime"
                data-testid={`edit-msg-input-${message.id}`}
                autoFocus
              />
              {editError && (
                <span className="text-xs text-danger">
                  {localizeMessage(
                    "screens",
                    editError ?? undefined,
                    "chat.failedToEdit",
                  )}
                </span>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsEditing(false)}
                  disabled={savingEdit}
                  className="rounded px-2.5 py-1 text-xs font-medium text-paper/80 hover:bg-white/10"
                >
                  {t("chat.cancel")}
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdit}
                  disabled={savingEdit || !editContent.trim()}
                  className="rounded bg-lime px-2.5 py-1 text-xs font-semibold text-ink shadow hover:bg-lime-dark disabled:opacity-50"
                  data-testid={`save-edit-btn-${message.id}`}
                >
                  {savingEdit ? t("chat.saving") : t("chat.save")}
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Message Content */}
              <div
                dir="auto"
                className="whitespace-pre-wrap break-words text-sm leading-relaxed"
                data-testid={`msg-content-${message.id}`}
              >
                {message.content}
              </div>

              {/* Message Meta Info: Timestamp, Edited badge, Status ticks */}
              <div
                className={`mt-1 flex items-center justify-end gap-1.5 text-[11px] ${
                  isOwn ? "text-paper/70" : "text-ink-muted"
                }`}
              >
                {message.edited_at && (
                  <span
                    className="italic opacity-80"
                    title={t("chat.editedTitle", {
                      time: formatTime(message.edited_at),
                    })}
                    data-testid={`edited-badge-${message.id}`}
                  >
                    {t("chat.edited")}
                  </span>
                )}

                <span data-testid={`msg-timestamp-${message.id}`}>
                  {formatTime(message.created_at)}
                </span>

                {/* Delivery / Read Status indicator for own messages */}
                {isOwn && (
                  <span
                    className="inline-flex items-center"
                    data-testid={`msg-status-${message.id}`}
                    title={t("chat.statusTitle", {
                      status: t(
                        {
                          sent: "chat.statusSent",
                          sending: "chat.statusSending",
                          failed: "chat.statusFailed",
                          delivered: "chat.statusDelivered",
                          read: "chat.statusRead",
                        }[message.status] ?? "chat.statusSent",
                      ),
                    })}
                  >
                    {message.status === "sending" && (
                      <svg
                        className="h-3 w-3 animate-spin text-white/70"
                        viewBox="0 0 24 24"
                        fill="none"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        />
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                        />
                      </svg>
                    )}
                    {message.status === "sent" && (
                      <span
                        className="text-xs font-semibold leading-none text-white/80"
                        aria-label={t("chat.statusSent")}
                      >
                        ✓
                      </span>
                    )}
                    {message.status === "delivered" && (
                      <span
                        className="text-xs font-semibold leading-none text-white/90"
                        aria-label={t("chat.statusDelivered")}
                      >
                        ✓✓
                      </span>
                    )}
                    {message.status === "read" && (
                      <span
                        className="text-xs font-extrabold leading-none text-sky-200"
                        aria-label={t("chat.statusRead")}
                      >
                        ✓✓
                      </span>
                    )}
                    {message.status === "failed" && (
                      <button
                        type="button"
                        onClick={() => onRetry?.(message)}
                        className="inline-flex items-center gap-1 text-red-200 hover:text-white"
                        title={t("chat.retrySendTitle")}
                        aria-label={t("chat.retrySendAria")}
                        data-testid={`retry-send-btn-${message.id}`}
                      >
                        <svg
                          className="h-3.5 w-3.5"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                          />
                        </svg>
                      </button>
                    )}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Delete confirmation modal / prompt */}
      {confirmDelete && (
        <div
          className="mt-1 flex items-center gap-2 rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-700 dark:bg-red-950/60 dark:text-red-300"
          data-testid={`delete-confirm-prompt-${message.id}`}
        >
          <span>{t("chat.deleteMessageConfirm")}</span>
          <button
            type="button"
            disabled={deleting}
            onClick={handleDelete}
            className="font-bold underline hover:text-red-900 disabled:opacity-50"
            data-testid={`confirm-delete-btn-${message.id}`}
          >
            {deleting ? t("chat.deleting") : t("chat.yesDelete")}
          </button>
          <button
            type="button"
            onClick={() => setConfirmDelete(false)}
            className="text-gray-500 hover:text-gray-700 dark:text-gray-400"
          >
            {t("chat.cancel")}
          </button>
        </div>
      )}
    </div>
  );
};
