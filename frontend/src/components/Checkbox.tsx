import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  description?: ReactNode;
  error?: string;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  {
    label,
    description,
    error,
    id: externalId,
    disabled,
    className = "",
    ...props
  },
  ref
) {
  const generatedId = useId();
  const checkboxId = externalId || generatedId;
  const errorId = `${checkboxId}-error`;
  const descId = `${checkboxId}-desc`;

  const ariaDescribedBy = [error ? errorId : null, description ? descId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="flex items-start text-start">
      <div className="flex items-center h-5">
        <input
          ref={ref}
          id={checkboxId}
          type="checkbox"
          disabled={disabled}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={ariaDescribedBy || undefined}
          className={`w-4 h-4 rounded border-border text-ink bg-surface transition-colors cursor-pointer
            focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2 focus-visible:outline-hidden
            disabled:opacity-50 disabled:cursor-not-allowed
            ${error ? "border-danger" : "border-border"}
            ${className}`}
          {...props}
        />
      </div>

      {label || description ? (
        <div className="ms-2.5 text-sm select-none">
          {label ? (
            <label
              htmlFor={checkboxId}
              className={`font-medium text-ink cursor-pointer ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
            >
              {label}
            </label>
          ) : null}

          {description ? (
            <p id={descId} className="text-xs text-ink-muted mt-0.5">
              {description}
            </p>
          ) : null}

          {error ? (
            <p id={errorId} role="alert" className="text-xs text-danger font-medium mt-0.5">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
});

