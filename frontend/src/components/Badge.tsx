import type { HTMLAttributes, ReactNode } from "react";

export type BadgeVariant =
  | "default"
  | "lime"
  | "success"
  | "danger"
  | "warning"
  | "info"
  | "outline";

export type BadgeSize = "sm" | "md";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  children: ReactNode;
  className?: string;
}

export function Badge({
  variant = "default",
  size = "md",
  children,
  className = "",
  ...props
}: BadgeProps) {
  const sizeStyles = {
    sm: "text-[11px] px-2 py-0.5",
    md: "text-xs px-2.5 py-1",
  }[size];

  const variantStyles = {
    default: "bg-ink text-paper",
    lime: "bg-lime text-ink font-semibold",
    success: "bg-success-subtle text-success border border-success/30",
    danger: "bg-danger-subtle text-danger border border-danger/30",
    warning: "bg-warning-subtle text-warning border border-warning/30",
    info: "bg-info-subtle text-info border border-info/30",
    outline: "border border-border text-ink bg-transparent",
  }[variant];

  return (
    <span
      className={`inline-flex items-center justify-center font-medium rounded-full select-none leading-none ${sizeStyles} ${variantStyles} ${className}`}
      {...props}
    >
      {children}
    </span>
  );
}
