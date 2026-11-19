import React from "react";
import { useText } from "../../i18n/useText";

export interface PresenceDotProps {
  isOnline: boolean;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
  showLabel?: boolean;
  labelClassName?: string;
}

const sizeClasses = {
  xs: "h-2 w-2",
  sm: "h-2.5 w-2.5",
  md: "h-3 w-3",
  lg: "h-3.5 w-3.5",
};

export const PresenceDot: React.FC<PresenceDotProps> = ({
  isOnline,
  size = "sm",
  className = "",
  showLabel = false,
  labelClassName = "text-xs text-ink-muted",
}) => {
  const { t } = useText();
  const label = t(isOnline ? "controls.online" : "controls.offline");
  const dotColorClass = isOnline ? "bg-emerald-500" : "bg-gray-400";
  const sizeClass = sizeClasses[size] || sizeClasses.sm;

  if (showLabel) {
    return (
      <span
        className={`inline-flex items-center space-x-1.5 ${className}`}
        data-testid="presence-indicator"
      >
        <span
          className={`inline-block rounded-full ${sizeClass} ${dotColorClass}`}
          aria-hidden="true"
          data-testid="presence-dot"
        />
        <span className={labelClassName} data-testid="presence-label">
          {label}
        </span>
      </span>
    );
  }

  return (
    <span
      className={`inline-block rounded-full ${sizeClass} ${dotColorClass} ${className}`}
      role="status"
      aria-label={label}
      data-testid="presence-dot"
    />
  );
};
