import React, { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { useText } from "../../i18n/useText";
import type { ApplicationItem } from "./types";

export interface ApplicationCardProps {
  application: ApplicationItem;
  onWithdraw: (id: number) => Promise<void>;
}

export const ApplicationCard: React.FC<ApplicationCardProps> = ({
  application,
  onWithdraw,
}) => {
  const { t } = useText();
  const [confirmWithdraw, setConfirmWithdraw] = useState(false);
  const [withdrawing, setWithdrawing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canWithdraw =
    application.status === "submitted" ||
    application.status === "viewed" ||
    application.status === "invited";

  const handleConfirmWithdraw = async () => {
    try {
      setWithdrawing(true);
      setError(null);
      await onWithdraw(application.id);
      setConfirmWithdraw(false);
    } catch (err: unknown) {
      const e = err as { message?: string };
      setError(e.message || t("applications.failedToWithdraw"));
    } finally {
      setWithdrawing(false);
    }
  };

  const getStatusBadge = (status: ApplicationItem["status"]) => {
    switch (status) {
      case "submitted":
        return (
          <Badge variant="neutral" data-testid="status-submitted">
            {t("applications.statusSubmitted")}
          </Badge>
        );
      case "viewed":
        return (
          <Badge variant="warning" data-testid="status-viewed">
            {t("applications.statusViewed")}
          </Badge>
        );
      case "invited":
        return (
          <Badge variant="success" data-testid="status-invited">
            {t("applications.statusInvited")}
          </Badge>
        );
      case "rejected":
        return (
          <Badge variant="danger" data-testid="status-rejected">
            {t("applications.statusRejected")}
          </Badge>
        );
      case "withdrawn":
        return (
          <Badge variant="neutral" data-testid="status-withdrawn">
            {t("applications.statusWithdrawn")}
          </Badge>
        );
      default:
        return <Badge variant="neutral">{status}</Badge>;
    }
  };

  const jobTitle = application.job_title || `Role #${application.job_id}`;
  const companyName =
    application.company_name || t("applications.defaultCompany");

  return (
    <Card
      className="overflow-hidden transition-shadow hover:shadow-md"
      data-testid={`application-card-${application.id}`}
    >
      <div className="p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                to={`/jobs/${application.job_id}`}
                className="truncate text-lg font-bold text-gray-900 hover:text-primary-600 hover:underline dark:text-gray-100 dark:hover:text-primary-400"
                data-testid={`job-link-${application.id}`}
              >
                {jobTitle}
              </Link>
              {getStatusBadge(application.status)}
            </div>

            <p className="mt-1 text-sm font-medium text-gray-600 dark:text-gray-400">
              {companyName}
            </p>

            <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-gray-400 dark:text-gray-500">
              <span>
                {t("applications.appliedDate", {
                  date: new Date(application.applied_at).toLocaleDateString(),
                })}
              </span>
              {application.viewed_at && (
                <span>
                  {t("applications.viewedDate", {
                    date: new Date(application.viewed_at).toLocaleDateString(),
                  })}
                </span>
              )}
            </div>

            {application.cover_note && (
              <div className="mt-3 rounded-lg bg-gray-50 p-3 text-xs text-gray-700 dark:bg-gray-800/60 dark:text-gray-300">
                <span className="font-semibold text-gray-500 dark:text-gray-400">
                  {t("applications.coverNote")}
                </span>
                <p className="mt-1 whitespace-pre-wrap">
                  {application.cover_note}
                </p>
              </div>
            )}
            {error && (
              <div className="mt-2 text-xs text-red-600 dark:text-red-400">
                {error}
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex shrink-0 flex-col items-end gap-2 sm:self-center">
            {application.conversation_id && (
              <Link to={`/chat/${application.conversation_id}`}>
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full sm:w-auto"
                  data-testid={`chat-link-btn-${application.id}`}
                >
                  {t("applications.openChat")}
                </Button>
              </Link>
            )}

            {canWithdraw && (
              <>
                {confirmWithdraw ? (
                  <div
                    className="flex items-center space-x-2 rounded-lg bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/60 dark:text-red-300"
                    data-testid={`withdraw-confirm-box-${application.id}`}
                  >
                    <span>{t("applications.withdrawPrompt")}</span>
                    <button
                      type="button"
                      disabled={withdrawing}
                      onClick={handleConfirmWithdraw}
                      className="font-bold underline hover:text-red-900 disabled:opacity-50"
                      data-testid={`confirm-withdraw-btn-${application.id}`}
                    >
                      {withdrawing
                        ? t("applications.withdrawing")
                        : t("applications.confirmWithdraw")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmWithdraw(false)}
                      className="text-gray-500 hover:text-gray-700 dark:text-gray-400"
                    >
                      {t("applications.cancel")}
                    </button>
                  </div>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setConfirmWithdraw(true)}
                    className="text-red-600 hover:text-red-700 dark:text-red-400"
                    data-testid={`withdraw-btn-${application.id}`}
                  >
                    {t("applications.withdraw")}
                  </Button>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
};
