import React, { useEffect, useRef, useState } from "react";
import { useText } from "../../i18n/useText";

export interface MessageInputProps {
  onSend: (content: string, idempotencyKey: string) => Promise<void>;
  disabled?: boolean;
  placeholder?: string;
}

const MAX_CHARS = 4000;
const WARNING_THRESHOLD = 200;

export const MessageInput: React.FC<MessageInputProps> = ({
  onSend,
  disabled = false,
  placeholder,
}) => {
  const { t } = useText();
  const inputPlaceholder = placeholder || t("chat.writeMessagePlaceholder");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea height
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const nextHeight = Math.min(el.scrollHeight, 160); // max ~5-6 rows
    el.style.height = `${Math.max(nextHeight, 40)}px`;
  }, [text]);

  const generateUUID = (): string => {
    if (
      typeof crypto !== "undefined" &&
      typeof crypto.randomUUID === "function"
    ) {
      return crypto.randomUUID();
    }
    // Fallback RFC4122 v4 UUID generator
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  };

  const handleSend = async () => {
    const trimmed = text.trim();
    if (!trimmed || sending || disabled) return;

    const idempotencyKey = generateUUID();
    setSending(true);

    try {
      setText("");
      if (textareaRef.current) {
        textareaRef.current.style.height = "40px";
      }
      await onSend(trimmed, idempotencyKey);
    } catch {
      // If error occurs, restore text so user doesn't lose their message
      setText(trimmed);
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const remainingChars = MAX_CHARS - text.length;
  const isNearLimit = remainingChars <= WARNING_THRESHOLD;

  return (
    <div
      className="border-t border-border bg-surface p-3"
      data-testid="message-input-container"
    >
      <div className="relative flex items-end gap-2">
        <div className="relative flex-1">
          <textarea
            ref={textareaRef}
            rows={1}
            dir="auto"
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
            onKeyDown={handleKeyDown}
            disabled={disabled || sending}
            placeholder={inputPlaceholder}
            aria-label={inputPlaceholder}
            maxLength={MAX_CHARS}
            className="w-full resize-none rounded-2xl border border-border bg-surface px-4 py-2.5 text-sm text-ink transition-colors focus:border-ink focus:bg-surface focus:outline-none focus:ring-1 focus:ring-ink disabled:opacity-50"
            data-testid="message-textarea"
          />

          {isNearLimit && (
            <span
              className={`absolute end-3 -top-5 text-[11px] font-medium ${
                remainingChars < 0
                  ? "text-danger"
                  : remainingChars < 50
                    ? "text-warning"
                    : "text-ink-muted"
              }`}
              data-testid="char-counter"
            >
              {t("chat.charsRemaining", { count: remainingChars })}
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={handleSend}
          disabled={disabled || sending || !text.trim()}
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink text-paper shadow-sm transition-all hover:bg-ink-muted focus:outline-none focus:ring-2 focus:ring-ink focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40"
          aria-label={t("chat.sendMessageAria")}
          data-testid="send-message-btn"
        >
          {sending ? (
            <svg
              className="h-4 w-4 animate-spin text-white"
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
          ) : (
            <svg
              className="h-4 w-4 directional-icon"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
};
