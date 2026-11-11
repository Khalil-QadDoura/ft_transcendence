import { forwardRef, useId, type SelectHTMLAttributes } from "react";

export interface SelectOption {
  value: string | number;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  helperText?: string;
  options?: SelectOption[];
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  function Select(
    {
      label,
      error,
      helperText,
      id: externalId,
      options,
      children,
      disabled,
      required,
      className = "",
      ...props
    },
    ref,
  ) {
    const generatedId = useId();
    const selectId = externalId || generatedId;
    const errorId = `${selectId}-error`;
    const helperId = `${selectId}-helper`;

    const ariaDescribedBy = [
      error ? errorId : null,
      helperText ? helperId : null,
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <div className="w-full text-start">
        {label ? (
          <label
            htmlFor={selectId}
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
          <select
            ref={ref}
            id={selectId}
            disabled={disabled}
            required={required}
            aria-invalid={error ? "true" : undefined}
            aria-describedby={ariaDescribedBy || undefined}
            className={`w-full appearance-none rounded-md border text-sm text-ink bg-surface transition-colors
            py-2 ps-3 pe-8
            ${error ? "border-danger focus-visible:ring-danger" : "border-border focus-visible:ring-ink"}
            focus-visible:ring-2 focus-visible:outline-hidden
            disabled:bg-paper-subtle disabled:text-ink-muted disabled:cursor-not-allowed
            cursor-pointer ${className}`}
            {...props}
          >
            {options
              ? options.map((opt) => (
                  <option
                    key={String(opt.value)}
                    value={opt.value}
                    disabled={opt.disabled}
                  >
                    {opt.label}
                  </option>
                ))
              : children}
          </select>

          <div className="absolute inset-y-0 end-0 flex items-center pe-2.5 pointer-events-none text-ink-muted">
            <svg
              className="w-4 h-4 fill-current"
              viewBox="0 0 20 20"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                clipRule="evenodd"
              />
            </svg>
          </div>
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
  },
);
