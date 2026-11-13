import { useText } from "../i18n/useText";
import { useState } from "react";

export type AvatarSize = "xs" | "sm" | "md" | "lg" | "xl";
export type AvatarStatus = "online" | "offline" | "away";

export interface AvatarProps {
  src?: string | null;
  alt: string;
  size?: AvatarSize;
  status?: AvatarStatus;
  fallbackText?: string;
  className?: string;
}

export function Avatar({
  src,
  alt,
  size = "md",
  status,
  fallbackText,
  className = "",
}: AvatarProps) {
  const { t } = useText();
  const [hasError, setHasError] = useState(false);

  const sizeClasses = {
    xs: "w-6 h-6 text-[10px]",
    sm: "w-8 h-8 text-xs",
    md: "w-10 h-10 text-sm",
    lg: "w-12 h-12 text-base",
    xl: "w-16 h-16 text-lg",
  }[size];

  const statusSizeClasses = {
    xs: "w-1.5 h-1.5",
    sm: "w-2 h-2",
    md: "w-2.5 h-2.5",
    lg: "w-3 h-3",
    xl: "w-3.5 h-3.5",
  }[size];

  const statusColorClasses = {
    online: "bg-success",
    offline: "bg-ink-muted",
    away: "bg-warning",
  };

  const getInitials = (text: string) => {
    return text
      .split(" ")
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase();
  };

  const showImage = src && !hasError;
  const initials = fallbackText || getInitials(alt);

  return (
    <div className={`relative inline-block shrink-0 select-none ${className}`}>
      <div
        className={`rounded-full overflow-hidden flex items-center justify-center font-semibold bg-paper-subtle text-ink border border-border ${sizeClasses}`}
      >
        {showImage ? (
          <img
            src={src}
            alt={alt}
            onError={() => setHasError(true)}
            className="w-full h-full object-cover"
          />
        ) : initials ? (
          <span>{initials}</span>
        ) : (
          <svg
            className="w-3/5 h-3/5 text-ink-muted fill-current"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
          </svg>
        )}
      </div>

      {status ? (
        <span
          title={t("controls.status", { status: t(`controls.${status}`) })}
          className={`absolute bottom-0 end-0 rounded-full ring-2 ring-surface ${statusSizeClasses} ${statusColorClasses[status]}`}
        />
      ) : null}
    </div>
  );
}
