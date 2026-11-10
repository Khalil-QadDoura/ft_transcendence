import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "outline" | "danger" | "ghost" | "lime";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  isLoading?: boolean;
  startIcon?: ReactNode;
  endIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    isLoading = false,
    disabled = false,
    startIcon,
    endIcon,
    children,
    className = "",
    type = "button",
    ...props
  },
  ref
) {
  const baseStyles =
    "inline-flex items-center justify-center font-medium transition-colors select-none rounded-md focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-ink focus-visible:outline-hidden disabled:opacity-50 disabled:pointer-events-none cursor-pointer";

  const sizeStyles = {
    sm: "text-xs px-2.5 py-1.5 gap-1.5",
    md: "text-sm px-4 py-2 gap-2",
    lg: "text-base px-5 py-2.5 gap-2.5",
  }[size];

  const variantStyles = {
    primary: "bg-ink text-paper hover:bg-ink/90 active:bg-ink/95",
    lime: "bg-lime text-ink font-semibold hover:bg-lime-dark active:bg-lime-dark/90",
    secondary: "bg-paper-subtle text-ink hover:bg-border active:bg-border/90 border border-border",
    outline: "border border-border bg-transparent text-ink hover:bg-paper-subtle active:bg-border-subtle",
    danger: "bg-danger text-white hover:bg-danger/90 active:bg-danger/95 focus-visible:ring-danger",
    ghost: "bg-transparent text-ink hover:bg-paper-subtle active:bg-border/60",
  }[variant];

  const isDisabled = disabled || isLoading;

  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={isLoading ? "true" : undefined}
      className={`${baseStyles} ${sizeStyles} ${variantStyles} ${className}`}
      {...props}
    >
      {isLoading ? (
        <Spinner size={size === "lg" ? "md" : "sm"} className="text-current me-1.5" />
      ) : startIcon ? (
        <span className="inline-flex shrink-0 me-1.5">{startIcon}</span>
      ) : null}
      <span>{children}</span>
      {!isLoading && endIcon ? (
        <span className="inline-flex shrink-0 ms-1.5">{endIcon}</span>
      ) : null}
    </button>
  );
});
