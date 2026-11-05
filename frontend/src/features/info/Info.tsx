import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Activity, ArrowRight, Server, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { Badge, Button, PageTitle } from "../../components/ui";
export function Status() {
  const { t } = useTranslation();
  const ping = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ ok: boolean }>("/ping"),
    refetchInterval: 30000,
    retry: false,
  });
  return (
    <>
      <PageTitle
        eyebrow="A LITTLE PEACE OF MIND"
        title="Behind every connection."
        description="A live check of the service that keeps your workspace moving."
      />
      <section className="panel narrow-panel">
        <div className="status-banner">
          <Activity size={32} />
          <h2>
            {t(
              ping.isPending
                ? "Checking connection…"
                : ping.data?.ok
                  ? "The API is reachable."
                  : "We’re having trouble connecting.",
            )}
          </h2>
        </div>
        <div className="application-row">
          <Server size={22} />
          <strong className="grow">{t("Application API")}</strong>
          <Badge tone={ping.data?.ok ? "" : "orange"}>
            {t(
              ping.isPending
                ? "Checking"
                : ping.data?.ok
                  ? "Operational"
                  : "Unavailable",
            )}
          </Badge>
        </div>
        <p className="muted">
          {t(
            "This checks API availability. Database, storage, email, and moderation require separate service checks.",
          )}
        </p>
        <Button
          variant="secondary"
          busy={ping.isFetching}
          onClick={() => void ping.refetch()}
        >
          {t("Check again")}
        </Button>
      </section>
    </>
  );
}
export function Legal({ kind }: { kind: "privacy" | "terms" }) {
  const { t } = useTranslation();
  return (
    <>
      <PageTitle
        eyebrow="TRUST IS PART OF THE EXPERIENCE"
        title={
          kind === "privacy"
            ? "Your privacy matters."
            : "A place for good people."
        }
      />
      <article className="panel prose narrow-panel">
        <ShieldCheck size={30} />
        <p className="notice">
          Development preview · This project’s operators must approve the final
          policy before public launch.
        </p>
        {kind === "privacy" ? (
          <>
            <h2>What this prototype processes</h2>
            <p>
              WOZU uses account details, profile information, job applications,
              conversations, and uploaded introductions to provide its features.
              When you apply, your profile and selected introduction are shared
              with the employer.
            </p>
            <h2>Video processing</h2>
            <p>
              Uploads may be stored in object storage and processed by a
              moderation worker. Depending on the backend configuration, that
              worker may send video audio or text to OpenAI services for
              transcription and moderation. Do not upload sensitive personal
              information to a development instance.
            </p>
            <h2>Browser storage</h2>
            <p>
              This frontend stores your language preference and saved job IDs
              locally on your device. Session tokens are stored in session
              storage for the current browser tab. Signing out clears the
              session. No advertising analytics are included in this frontend.
            </p>
            <h2>Control over your information</h2>
            <p>
              You can edit your profile, remove your introductions, and
              deactivate your account from Settings. Deactivation is not a
              guarantee that all server records or backups have been erased.
              Contact the project operators for access, deletion, and retention
              questions before using this development service.
            </p>
          </>
        ) : (
          <>
            <h2>A development project</h2>
            <p>
              WOZU is an educational prototype, not a production recruitment
              service. Features may change and development data may be reset.
              Use test accounts and non-sensitive content while evaluating it.
            </p>
            <h2>Be accurate and respectful</h2>
            <p>
              Use truthful profile and job information. Upload only content you
              have permission to use. Do not harass other users, share another
              person’s private information, or attempt to bypass access
              controls.
            </p>
            <h2>Applications and conversations</h2>
            <p>
              Employers are responsible for the opportunities they publish. An
              application or conversation does not guarantee an interview or
              employment. Do not send payments or confidential documents through
              this prototype.
            </p>
            <h2>Game participation</h2>
            <p>
              Turing Duel is a social deduction game with anonymous participants
              and possible automated opponents. Follow the published game rules
              and keep conversations respectful.
            </p>
          </>
        )}
        <Link className="text-link" to="/settings">
          {t("Manage your account")}
          <ArrowRight size={16} />
        </Link>
      </article>
    </>
  );
}
export function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="not-found">
      <span>
        404<span>✳</span>
      </span>
      <h1>{t("A little off the beaten path.")}</h1>
      <p>{t("This page isn’t here, but your next opportunity might be.")}</p>
      <Link className="button primary" to="/jobs">
        {t("Back to discovery")}
        <ArrowRight size={17} />
      </Link>
    </div>
  );
}
