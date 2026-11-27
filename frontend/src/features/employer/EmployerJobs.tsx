import { localizeMessage } from "../../i18n/copy";
import "../../i18n";
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { formatNumber } from "../../i18n";
import { Button } from "../../components/Button";
import { Input } from "../../components/Input";
import { Select } from "../../components/Select";
import { Textarea } from "../../components/Textarea";
import { Modal } from "../../components/Modal";
import { employerApi, jobForm, type OwnedJob } from "./api";
import "./employer.css";
const key = ["employer", "jobs"];
export function EmployerJobs() {
  const { t } = useTranslation("employer");
  const cache = useQueryClient();
  const navigate = useNavigate();
  const { id } = useParams();
  const { pathname } = useLocation();
  const editing = pathname.endsWith("/edit");
  const creating = pathname.endsWith("/new");
  const jobs = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => employerApi.list(signal),
    retry: false,
  });
  const [target, setTarget] = useState<OwnedJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = jobs.data?.find((j) => String(j.id) === id);
  async function remove() {
    if (!target || busy) return;
    setBusy(true);
    setError("");
    try {
      await employerApi.remove(target.id);
      setTarget(null);
      await cache.invalidateQueries({ queryKey: key });
      await cache.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setTarget(null);
        setError(t("changed"));
        await cache.invalidateQueries({ queryKey: key });
      } else setError(t("actionError"));
    } finally {
      setBusy(false);
    }
  }
  if (jobs.isPending)
    return (
      <section className="employer-page" aria-busy="true">
        <p role="status">{t("loading")}</p>
      </section>
    );
  if (jobs.isError)
    return (
      <section className="employer-page">
        <h1>{t("title")}</h1>
        <p role="alert">
          {t(
            jobs.error instanceof ApiError && jobs.error.status === 404
              ? "companyRequired"
              : "loadError",
          )}
        </p>
        <div className="employer-actions">
          <Button onClick={() => void jobs.refetch()}>{t("retry")}</Button>
          {jobs.error instanceof ApiError && jobs.error.status === 404 && (
            <Link to="/company">{t("company:createCta")}</Link>
          )}
        </div>
      </section>
    );
  if (editing && !selected)
    return (
      <section className="employer-page">
        <h1>{t("missing")}</h1>
        <Link to="/employer/jobs">{t("back")}</Link>
      </section>
    );
  if (creating || editing)
    return (
      <JobEditor
        key={creating ? "new" : id}
        job={selected}
        onSaved={async () => {
          await cache.invalidateQueries({ queryKey: key });
          await cache.invalidateQueries({ queryKey: ["jobs"] });
          void navigate("/employer/jobs");
        }}
      />
    );
  const items = jobs.data ?? [];
  return (
    <section className="employer-page">
      <header className="employer-heading">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h1>{t("title")}</h1>
          <p>{t("intro")}</p>
        </div>
        <Link className="button" to="/employer/jobs/new">
          {t("create")}{" "}
          <span className="directional-icon" aria-hidden="true">
            ↗
          </span>
        </Link>
      </header>
      <div className="employer-stats">
        {["listings", "views", "applications"].map((label, i) => (
          <div key={label}>
            <strong>
              {formatNumber(
                i === 0
                  ? items.length
                  : items.reduce(
                      (sum, j) =>
                        sum + (i === 1 ? j.views_count : j.applications_count),
                      0,
                    ),
              )}
            </strong>
            <span>{t(label)}</span>
          </div>
        ))}
      </div>
      {error && !target && (
        <p role="alert">{localizeMessage("employer", error)}</p>
      )}
      {items.length === 0 ? (
        <div className="employer-empty">
          <span aria-hidden="true">✳</span>
          <h2>{t("empty")}</h2>
          <p>{t("emptyHint")}</p>
        </div>
      ) : (
        <div className="employer-list">
          {items.map((job) => (
            <article className="employer-job" key={job.id}>
              <div>
                <span className={`employer-status ${job.status}`}>
                  {t(job.status)}
                </span>
                <h2>
                  <bdi>{job.title}</bdi>
                </h2>
                <p dir="auto">{job.location || t("noLocation")}</p>
              </div>
              <dl>
                {[
                  "views_count",
                  "applications_count",
                  "new_applications_count",
                ].map((k) => (
                  <div key={k}>
                    <dt>{t(k)}</dt>
                    <dd>{formatNumber(job[k as "views_count"])}</dd>
                  </div>
                ))}
              </dl>
              <div className="employer-actions">
                <Link
                  className="button light"
                  to={`/employer/jobs/${job.id}/edit`}
                  aria-label={t("editNamed", { title: job.title })}
                >
                  {t("edit")}
                </Link>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setError("");
                    setTarget(job);
                  }}
                  aria-label={t("deleteNamed", { title: job.title })}
                >
                  {t("delete")}
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
      <Modal
        isOpen={!!target}
        onClose={() => {
          if (!busy) setTarget(null);
        }}
        title={t("deleteTitle")}
        description={t("deleteHint", { title: target?.title })}
      >
        {error && <p role="alert">{localizeMessage("employer", error)}</p>}
        <div className="employer-actions">
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => void remove()}
          >
            {t("confirmDelete")}
          </Button>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => setTarget(null)}
          >
            {t("cancel")}
          </Button>
        </div>
      </Modal>
    </section>
  );
}
function JobEditor({
  job,
  onSaved,
}: {
  job?: OwnedJob;
  onSaved: () => Promise<void>;
}) {
  const { t } = useTranslation("employer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const values: Record<string, FormDataEntryValue> = {};
    new FormData(e.currentTarget).forEach((value, key) => {
      values[key] = value;
    });
    const parsed = jobForm.safeParse(values);
    if (!parsed.success) {
      setErrors(
        Object.fromEntries(
          parsed.error.issues.map((i) => [String(i.path[0]), t("invalid")]),
        ),
      );
      setError(t("checkFields"));
      return;
    }
    setBusy(true);
    setError("");
    setErrors({});
    try {
      await employerApi.save(parsed.data, job?.id);
      await onSaved();
    } catch (cause) {
      setError(
        t(
          cause instanceof ApiError && cause.status === 404
            ? "changed"
            : cause instanceof ApiError && cause.status === 422
              ? "checkFields"
              : "actionError",
        ),
      );
    } finally {
      setBusy(false);
    }
  }
  const select = (
    name: "status" | "schedule" | "salary_type" | "urgency",
    values: string[],
    fallback: string,
  ) => (
    <Select
      name={name}
      label={t(name)}
      defaultValue={job?.[name] ?? fallback}
      options={values.map((value) => ({ value, label: t(value) }))}
      error={errors[name]}
    />
  );
  return (
    <section className="employer-page">
      <Link className="employer-back" to="/employer/jobs">
        {t("back")}
      </Link>
      <header className="employer-heading">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h1>{t(job ? "editTitle" : "createTitle")}</h1>
          <p>{t("editorHint")}</p>
        </div>
      </header>
      <form className="employer-form" onSubmit={(e) => void submit(e)}>
        <fieldset disabled={busy}>
          <legend>{t("details")}</legend>
          {error && <p role="alert">{localizeMessage("employer", error)}</p>}
          <Input
            name="title"
            label={t("jobTitle")}
            defaultValue={job?.title ?? ""}
            required
            maxLength={200}
            error={localizeMessage("employer", errors.title)}
          />
          <Textarea
            name="description"
            label={t("description")}
            defaultValue={job?.description ?? ""}
            rows={7}
            error={localizeMessage("employer", errors.description)}
          />
          <div className="employer-fields">
            <Input
              name="location"
              label={t("location")}
              defaultValue={job?.location ?? ""}
              maxLength={150}
              error={localizeMessage("employer", errors.location)}
            />
            {select(
              "schedule",
              ["full_time", "part_time", "internship"],
              "full_time",
            )}
            <Input
              name="latitude"
              label={t("latitude")}
              type="number"
              step="any"
              min={-90}
              max={90}
              required
              defaultValue={job?.latitude ?? ""}
              error={localizeMessage("employer", errors.latitude)}
            />
            <Input
              name="longitude"
              label={t("longitude")}
              type="number"
              step="any"
              min={-180}
              max={180}
              required
              defaultValue={job?.longitude ?? ""}
              error={localizeMessage("employer", errors.longitude)}
            />
          </div>
          <p className="employer-hint">{t("coordinatesHint")}</p>
          <div className="employer-fields">
            <Input
              name="salary_amount"
              label={t("salary")}
              inputMode="decimal"
              defaultValue={job?.salary_amount ?? ""}
              error={localizeMessage("employer", errors.salary_amount)}
            />
            <Input
              name="salary_currency"
              label={t("currency")}
              maxLength={3}
              defaultValue={job?.salary_currency ?? ""}
              error={localizeMessage("employer", errors.salary_currency)}
            />
            {select(
              "salary_type",
              ["hourly", "daily", "weekly", "monthly"],
              "monthly",
            )}
            {select("urgency", ["normal", "urgent", "hot"], "normal")}
            {select("status", ["draft", "open"], "draft")}
          </div>
          <div className="employer-actions">
            <Button type="submit" isLoading={busy}>
              {t("save")}
            </Button>
            <Link to="/employer/jobs">{t("cancel")}</Link>
          </div>
        </fieldset>
      </form>
    </section>
  );
}
