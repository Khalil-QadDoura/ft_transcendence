import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  startAddon?: ReactNode;
  endAddon?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    label,
    error,
    helperText,
    id: externalId,
    startAddon,
    endAddon,
    disabled,
    required,
    className = "",
    ...props
  },
  ref,
) {
  const generatedId = useId();
  const inputId = externalId || generatedId;
  const errorId = `${inputId}-error`;
  const helperId = `${inputId}-helper`;

  const ariaDescribedBy = [error ? errorId : null, helperText ? helperId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="w-full text-start">
      {label ? (
        <label
          htmlFor={inputId}
          className="block text-sm font-medium text-ink mb-1 select-none"
        >
          {label}
          {required ? (
            <span className="text-danger ms-1" aria-hidden="true">
              *
            </span>
          ) : null}
        </label>
      ) : null}

      <div className="relative flex items-center">
        {startAddon ? (
          <div className="absolute inset-y-0 start-0 flex items-center ps-3 pointer-events-none text-ink-muted">
            {startAddon}
          </div>
        ) : null}

        <input
          ref={ref}
          id={inputId}
          disabled={disabled}
          required={required}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={ariaDescribedBy || undefined}
          className={`w-full rounded-md border text-sm text-ink bg-surface placeholder:text-ink-muted/60 transition-colors
            py-2 px-3
            ${startAddon ? "ps-9" : "ps-3"}
            ${endAddon ? "pe-9" : "pe-3"}
            ${error ? "border-danger focus-visible:ring-danger" : "border-border focus-visible:ring-ink"}
            focus-visible:ring-2 focus-visible:outline-hidden
            disabled:bg-paper-subtle disabled:text-ink-muted disabled:cursor-not-allowed
            ${className}`}
          {...props}
        />

        {endAddon ? (
          <div className="absolute inset-y-0 end-0 flex items-center pe-3 pointer-events-none text-ink-muted">
            {endAddon}
          </div>
        ) : null}
      </div>

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
});
