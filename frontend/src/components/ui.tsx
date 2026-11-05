import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type ButtonHTMLAttributes,
} from "react";
import {
  AlertCircle,
  ArrowRight,
  Check,
  LoaderCircle,
  SearchX,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
export function Button({
  children,
  variant = "primary",
  busy,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  busy?: boolean;
}) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className={`button ${variant} ${className}`}
    >
      {busy && <LoaderCircle size={16} className="spin" />}
      {children}
    </button>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <div className="notice error" role="alert">
      <AlertCircle size={19} />
      <div>
        {error instanceof Error
          ? error.message
          : t("Something went wrong. Please try again.")}
        {retry && (
          <button className="text-button" onClick={retry}>
            {t("Try again")}
          </button>
        )}
      </div>
    </div>
  );
}
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="empty">
      <div className="empty-icon">
        <SearchX size={27} />
      </div>
      <h3>{t(title)}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Loading() {
  const { t } = useTranslation();
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" />
      {t("Loading…")}
    </div>
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <header className="page-title">
      <div>
        {eyebrow && <span className="eyebrow">{t(eyebrow)}</span>}
        <h1>{t(title)}</h1>
        {description && <p>{t(description)}</p>}
      </div>
      {action}
    </header>
  );
}
export function Avatar({
  name,
  size = "",
  url,
}: {
  name: string;
  size?: string;
  url?: string | null;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={`avatar ${size}`} aria-hidden="true">
      {url && !failed ? (
        <img src={url} alt="" onError={() => setFailed(true)} />
      ) : (
        name
          .split(" ")
          .filter(Boolean)
          .slice(0, 2)
          .map((x) => x[0])
          .join("")
          .toUpperCase() || "W"
      )}
    </span>
  );
}
export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Field({
  label,
  children,
  error,
  hint,
}: {
  label: string;
  children: ReactNode;
  error?: string;
  hint?: string;
}) {
  const { t } = useTranslation();
  return (
    <label className="field">
      <span>{t(label)}</span>
      {children}
      {hint && <small>{t(hint)}</small>}
      {error && (
        <small className="field-error" role="alert">
          {t(error)}
        </small>
      )}
    </label>
  );
}
export function useAction<T = void>(
  fn: (value: T) => Promise<unknown>,
  keys: string[] = [],
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      for (const key of keys)
        await client.invalidateQueries({ queryKey: [key] });
    },
  });
}
export function Success({ children }: { children: ReactNode }) {
  return (
    <div className="notice success" role="status">
      <Check size={18} />
      {children}
    </div>
  );
}
export function Confirm({
  title,
  description,
  onConfirm,
  children,
  danger = false,
}: {
  title: string;
  description: string;
  onConfirm: () => Promise<unknown>;
  children: ReactNode;
  danger?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const action = useAction(async () => {
    await onConfirm();
    setOpen(false);
  });
  const { t } = useTranslation();
  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);
  return (
    <>
      <button
        className={`button ${danger ? "danger" : "secondary"}`}
        aria-label={typeof children === "string" ? undefined : t(title)}
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
      <dialog
        ref={dialog}
        className="modal"
        aria-label={t(title)}
        onCancel={(e) => {
          if (action.isPending) e.preventDefault();
          else setOpen(false);
        }}
        onClose={() => setOpen(false)}
      >
        <div className="modal-card">
          <button
            aria-label={t("Close")}
            className="icon-button modal-close"
            onClick={() => setOpen(false)}
            disabled={action.isPending}
          >
            <X size={20} />
          </button>
          <h2>{t(title)}</h2>
          <p>{t(description)}</p>
          <ErrorNotice error={action.error} />
          <div className="actions">
            <Button
              variant="secondary"
              onClick={() => setOpen(false)}
              disabled={action.isPending}
            >
              {t("Cancel")}
            </Button>
            <Button
              variant={danger ? "danger" : "primary"}
              busy={action.isPending}
              onClick={() => action.mutate()}
            >
              {t("Confirm")}
            </Button>
          </div>
        </div>
      </dialog>
    </>
  );
}
export function TextLink({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link className="text-link" to={to}>
      {children}
      <ArrowRight size={16} />
    </Link>
  );
}
export function money(
  amount: string | number | null | undefined,
  currency?: string | null,
) {
  if (amount == null) return null;
  try {
    return new Intl.NumberFormat(
      localStorage.getItem("wozu.language") || "en",
      {
        style: "currency",
        currency: currency || "USD",
        maximumFractionDigits: 0,
      },
    ).format(Number(amount));
  } catch {
    return `${amount} ${currency || ""}`;
  }
}
export function dateLabel(value: string) {
  return new Intl.DateTimeFormat(
    localStorage.getItem("wozu.language") || "en",
    { month: "short", day: "numeric" },
  ).format(new Date(value));
}
