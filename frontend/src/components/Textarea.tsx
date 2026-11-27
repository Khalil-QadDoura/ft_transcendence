import { forwardRef, useId, type TextareaHTMLAttributes } from "react";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  helperText?: string;
  showCount?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    {
      label,
      error,
      helperText,
      id: externalId,
      maxLength,
      value,
      showCount = false,
      disabled,
      required,
      rows = 4,
      className = "",
      ...props
    },
    ref,
  ) {
    const generatedId = useId();
    const textareaId = externalId || generatedId;
    const errorId = `${textareaId}-error`;
    const helperId = `${textareaId}-helper`;

    const ariaDescribedBy = [
      error ? errorId : null,
      helperText ? helperId : null,
    ]
      .filter(Boolean)
      .join(" ");

    const currentLength = typeof value === "string" ? value.length : 0;

    return (
      <div className="w-full text-start">
        <div className="flex justify-between items-center mb-1">
          {label ? (
            <label
              htmlFor={textareaId}
              className="block text-sm font-medium text-ink select-none"
            >
              {label}
              {required ? (
                <span className="text-danger ms-1" aria-hidden="true">
                  *
                </span>
              ) : null}
            </label>
          ) : null}

          {showCount && maxLength ? (
            <span className="text-xs text-ink-muted ms-auto">
              {currentLength}/{maxLength}
            </span>
          ) : null}
        </div>

        <textarea
          dir="auto"
          ref={ref}
          id={textareaId}
          rows={rows}
          maxLength={maxLength}
          value={value}
          disabled={disabled}
          required={required}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={ariaDescribedBy || undefined}
          className={`w-full rounded-md border text-sm text-ink bg-surface placeholder:text-ink-muted/60 transition-colors
          py-2 px-3
          ${error ? "border-danger focus-visible:ring-danger" : "border-border focus-visible:ring-ink"}
          focus-visible:ring-2 focus-visible:outline-hidden
          disabled:bg-paper-subtle disabled:text-ink-muted disabled:cursor-not-allowed
          ${className}`}
          {...props}
        />

        {error ? (
          <p
            id={errorId}
            role="alert"
            className="mt-1 text-xs text-danger font-medium"
          >
            {error}
          </p>
        ) : helperText ? (
          <p id={helperId} className="mt-1 text-xs text-ink-muted">
            {helperText}
          </p>
        ) : null}
      </div>
    );
  },
);
