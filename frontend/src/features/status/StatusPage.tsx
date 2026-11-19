import { useTranslation } from "react-i18next";
import { Badge, type BadgeVariant, Card, CardContent } from "../../components";
import { formatDate, formatNumber } from "../../i18n";
import { STATUS_COMPONENTS, type ComponentState } from "./api";
import {
  overallStatus,
  STATUS_POLL_INTERVAL_MS,
  useHealthStatus,
  type OverallStatus,
} from "./useHealthStatus";

// Color never stands alone: every state also has an icon and a text label.
const STATE_STYLE: Record<
  ComponentState,
  { variant: BadgeVariant; icon: string }
> = {
  up: { variant: "success", icon: "✓" },
  down: { variant: "danger", icon: "✕" },
  unknown: { variant: "outline", icon: "?" },
};

const OVERALL_STYLE: Record<
  OverallStatus,
  { className: string; icon: string }
> = {
  operational: {
    className: "bg-success-subtle text-success border-success/30",
    icon: "✓",
  },
  degraded: {
    className: "bg-warning-subtle text-warning border-warning/30",
    icon: "!",
  },
  unreachable: {
    className: "bg-danger-subtle text-danger border-danger/30",
    icon: "✕",
  },
  checking: {
    className: "bg-paper-subtle text-ink-muted border-border",
    icon: "…",
  },
};

function StateBadge({ state }: { state: ComponentState }) {
  const { t } = useTranslation("status");
  const { variant, icon } = STATE_STYLE[state];
  return (
    <Badge
      variant={variant}
      className={`gap-1.5 shrink-0 ${state === "unknown" ? "text-ink-muted" : ""}`}
      data-state={state}
    >
      <span aria-hidden="true">{icon}</span>
      {t(`state.${state}`)}
    </Badge>
  );
}

export function StatusPage() {
  const { t } = useTranslation("status");
  const { data } = useHealthStatus();
  const overall = overallStatus(data);
  const banner = OVERALL_STYLE[overall];
  const seconds = formatNumber(STATUS_POLL_INTERVAL_MS / 1000);
  // Before the first answer every component is "unknown" (grey), in the fixed order.
  const components =
    data?.components ??
    STATUS_COMPONENTS.map((id) => ({
      id,
      state: "unknown" as const,
    }));

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6 text-start">
      <div className="space-y-1">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-ink">
          {t("title")}
        </h1>
        <p className="text-sm text-ink-muted leading-relaxed">
          {t("intro", { seconds })}
        </p>
      </div>

      <div aria-live="polite">
        <p
          className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-base font-semibold ${banner.className}`}
          data-overall={overall}
        >
          <span aria-hidden="true">{banner.icon}</span>
          {t(`overall.${overall}`)}
        </p>
      </div>

      <Card>
        <CardContent className="space-y-2">
          <h2
            id="status-components"
            className="text-sm font-semibold text-ink-muted"
          >
            {t("componentsHeading")}
          </h2>
          <ul
            aria-labelledby="status-components"
            className="divide-y divide-border-subtle"
          >
            {components.map(({ id, state }) => (
              <li
                key={id}
                data-component={id}
                className="flex items-center justify-between gap-3 py-3"
              >
                <span className="text-sm font-medium text-ink min-w-0">
                  {t(`component.${id}`)}
                </span>
                <StateBadge state={state} />
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <p className="text-xs text-ink-muted" data-last-checked>
        {data ? (
          <>
            {t("lastChecked")}{" "}
            <time dateTime={new Date(data.checkedAt).toISOString()}>
              {formatDate(new Date(data.checkedAt), { timeStyle: "medium" })}
            </time>
          </>
        ) : (
          t("notChecked")
        )}
      </p>
    </div>
  );
}
