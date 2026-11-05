import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowUpRight,
  Building2,
  Eye,
  FileText,
  Pencil,
  Plus,
  Play,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  api,
  ApiError,
  patch,
  post,
  query,
  remove,
  type Company,
  type Job,
  type Schema,
} from "../../api/client";
import {
  Badge,
  Button,
  Confirm,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  PageTitle,
  Success,
  dateLabel,
  money,
  useAction,
} from "../../components/ui";

function useCompany() {
  return useQuery({
    queryKey: ["company"],
    queryFn: async () => {
      try {
        return await api<Company | null>("/companies/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
  });
}
export function Employer() {
  const { t } = useTranslation();
  const company = useCompany();
  const [editCompany, setEditCompany] = useState(false);
  const jobs = useQuery({
    queryKey: ["employer-jobs"],
    queryFn: () => api<Job[]>("/jobs/mine"),
    enabled: !!company.data,
  });
  const drop = useAction(
    (id: number) => remove(`/jobs/${id}`),
    ["employer-jobs", "jobs"],
  );
  if (company.isPending) return <Loading />;
  return (
    <>
      <PageTitle
        eyebrow="BUILD SOMETHING WITH GOOD PEOPLE"
        title="Your next great hire starts here."
        description="Put your team out there. Let the right people find you."
        action={
          company.data && (
            <Link className="button primary" to="/employer/jobs/new">
              <Plus size={17} />
              {t("Post an opportunity")}
            </Link>
          )
        }
      />
      <ErrorNotice error={company.error || jobs.error} />
      {!company.data || editCompany ? (
        <CompanyForm
          company={company.data || undefined}
          onDone={() => setEditCompany(false)}
        />
      ) : (
        <>
          <section className="company-banner">
            <span className="company-mark large">
              <Building2 size={30} />
            </span>
            <div className="grow">
              <span className="eyebrow">{t("YOUR COMPANY")}</span>
              <h2>{company.data.name}</h2>
              <p>
                {[company.data.city, company.data.country]
                  .filter(Boolean)
                  .join(", ")}
              </p>
            </div>
            <Button variant="secondary" onClick={() => setEditCompany(true)}>
              <Pencil size={15} />
              {t("Edit company")}
            </Button>
          </section>
          <div className="stats-grid">
            {[
              {
                label: "Active opportunities",
                value:
                  jobs.data?.filter((j) => j.status === "open").length || 0,
                icon: FileText,
              },
              {
                label: "Total applications",
                value:
                  jobs.data?.reduce((n, j) => n + j.applications_count, 0) || 0,
                icon: Users,
              },
              {
                label: "Opportunity views",
                value: jobs.data?.reduce((n, j) => n + j.views_count, 0) || 0,
                icon: Eye,
              },
            ].map(({ label, value, icon: Icon }) => (
              <div className="stat-card" key={label}>
                <Icon size={21} />
                <span>{t(label)}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <section className="panel">
            <div className="section-heading">
              <h2>{t("Your opportunities")}</h2>
              <Badge tone="neutral">{jobs.data?.length || 0}</Badge>
            </div>
            {jobs.isPending && <Loading />}
            {jobs.data?.map((j) => (
              <article className="employer-job" key={j.id}>
                <div className="grow">
                  <div className="actions">
                    <h3>{j.title}</h3>
                    <Badge>
                      {t(j.status === "active" ? "draft" : j.status)}
                    </Badge>
                  </div>
                  <p>
                    {j.location} ·{" "}
                    {money(j.salary_amount, j.salary_currency) ||
                      t("Salary on request")}{" "}
                    · {j.applications_count} {t("applications")}
                  </p>
                </div>
                <Link
                  className="button secondary small"
                  to={`/employer/jobs/${j.id}/applications`}
                >
                  {t("Applicants")}
                  <ArrowUpRight size={15} />
                </Link>
                <Link
                  className="icon-button"
                  to={`/employer/jobs/${j.id}/edit`}
                  aria-label={`${t("Edit job")}: ${j.title}`}
                >
                  <Pencil size={17} />
                </Link>
                <Confirm
                  title="Delete opportunity?"
                  description="This role will no longer be visible to candidates."
                  danger
                  onConfirm={() => drop.mutateAsync(j.id)}
                >
                  {t("Delete")}
                </Confirm>
              </article>
            ))}
            {!jobs.isPending && !jobs.data?.length && (
              <Empty
                title="Make room for your next great hire"
                action={
                  <Link className="button primary" to="/employer/jobs/new">
                    {t("Post an opportunity")}
                    <Plus size={17} />
                  </Link>
                }
              >
                {t(
                  "Tell people what you’re building and who you’d love to build it with.",
                )}
              </Empty>
            )}
          </section>
        </>
      )}
    </>
  );
}
function CompanyForm({
  company,
  onDone,
}: {
  company?: Company;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(company?.name || "");
  const [description, setDescription] = useState(company?.description || "");
  const [country, setCountry] = useState(company?.country || "");
  const [city, setCity] = useState(company?.city || "");
  const [district, setDistrict] = useState(company?.district || "");
  const save = useAction(async () => {
    if (company)
      await patch("/companies/me", {
        name,
        country,
        city,
        district: district || null,
      });
    else
      await post("/companies", {
        name,
        description: description || null,
        country,
        city,
        district: district || null,
      });
    onDone();
  }, ["company"]);
  return (
    <section className="panel narrow-panel">
      <span className="eyebrow">{t("GOOD TEAMS START WITH A STORY")}</span>
      <h2>{t(company ? "Your company profile" : "Meet your future team.")}</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Company name">
          <input
            required
            minLength={1}
            maxLength={150}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        {!company && (
          <Field label="About your company">
            <textarea
              maxLength={2000}
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        )}
        <div className="form-grid">
          <Field label="Country">
            <input
              required
              maxLength={100}
              value={country}
              onChange={(e) => setCountry(e.target.value)}
            />
          </Field>
          <Field label="City">
            <input
              required
              maxLength={100}
              value={city}
              onChange={(e) => setCity(e.target.value)}
            />
          </Field>
        </div>
        <Field label="District">
          <input
            maxLength={100}
            value={district}
            onChange={(e) => setDistrict(e.target.value)}
          />
        </Field>
        <ErrorNotice error={save.error} />
        <Button busy={save.isPending} type="submit">
          {t(company ? "Save company" : "Create company")}
          <ArrowUpRight size={17} />
        </Button>
      </form>
    </section>
  );
}
export function JobEditor() {
  const { id } = useParams();
  const job = useQuery({
    queryKey: ["job", id],
    queryFn: () => api<Job>(`/jobs/${id}`),
    enabled: !!id,
  });
  if (id && job.isPending) return <Loading />;
  if (job.error) return <ErrorNotice error={job.error} />;
  return <JobForm key={job.data?.id || "new"} job={job.data} />;
}
function JobForm({ job }: { job?: Job }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [draft, setDraft] = useState({
    title: job?.title || "",
    description: job?.description || "",
    location: job?.location || "",
    latitude: String(job?.latitude ?? ""),
    longitude: String(job?.longitude ?? ""),
    salary_amount: String(job?.salary_amount ?? ""),
    salary_currency: job?.salary_currency || "AED",
    salary_type: job?.salary_type || "monthly",
    schedule: job?.schedule || "full_time",
    urgency: job?.urgency || "normal",
    status: job?.status === "open" ? "open" : "active",
  });
  const set = (key: keyof typeof draft, value: string) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const save = useAction(async () => {
    const data = {
      ...draft,
      latitude: Number(draft.latitude),
      longitude: Number(draft.longitude),
      salary_amount: draft.salary_amount ? Number(draft.salary_amount) : null,
    };
    if (job) await patch(`/jobs/${job.id}`, data);
    else await post("/jobs", data);
    navigate("/employer");
  }, ["employer-jobs", "jobs", "job"]);
  return (
    <>
      <PageTitle
        eyebrow="OPEN A NEW DOOR"
        title={
          job ? "Refine your opportunity." : "Find your next great teammate."
        }
      />
      <form
        className="panel job-editor"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="section-heading">
          <h2>{t("The opportunity")}</h2>
          <Badge>
            {t(draft.status === "active" ? "Draft" : "Open for applications")}
          </Badge>
        </div>
        <Field label="Job title">
          <input
            required
            maxLength={200}
            value={draft.title}
            onChange={(e) => set("title", e.target.value)}
            placeholder={t("A clear title for a great opportunity")}
          />
        </Field>
        <Field label="Tell candidates about the role">
          <textarea
            required
            rows={8}
            maxLength={20000}
            value={draft.description}
            onChange={(e) => set("description", e.target.value)}
          />
        </Field>
        <Field label="Location">
          <input
            required
            maxLength={150}
            value={draft.location}
            onChange={(e) => set("location", e.target.value)}
            placeholder="Abu Dhabi, UAE"
          />
        </Field>
        <div className="form-grid">
          <Field label="Latitude">
            <input
              required
              type="number"
              step="any"
              min={-90}
              max={90}
              value={draft.latitude}
              onChange={(e) => set("latitude", e.target.value)}
            />
          </Field>
          <Field label="Longitude">
            <input
              required
              type="number"
              step="any"
              min={-180}
              max={180}
              value={draft.longitude}
              onChange={(e) => set("longitude", e.target.value)}
            />
          </Field>
        </div>
        <div className="form-grid three">
          <Field label="Salary amount">
            <input
              type="number"
              min={0}
              step="0.01"
              value={draft.salary_amount}
              onChange={(e) => set("salary_amount", e.target.value)}
            />
          </Field>
          <Field label="Currency">
            <input
              required
              pattern="[A-Z]{3}"
              maxLength={3}
              value={draft.salary_currency}
              onChange={(e) =>
                set("salary_currency", e.target.value.toUpperCase())
              }
            />
          </Field>
          <Field label="Salary period">
            <select
              value={draft.salary_type}
              onChange={(e) => set("salary_type", e.target.value)}
            >
              {["hourly", "daily", "weekly", "monthly"].map((s) => (
                <option key={s} value={s}>
                  {t(s)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="form-grid three">
          <Field label="Work schedule">
            <select
              value={draft.schedule}
              onChange={(e) => set("schedule", e.target.value)}
            >
              {["full_time", "part_time", "internship"].map((s) => (
                <option key={s} value={s}>
                  {t(s.replaceAll("_", " "))}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Urgency">
            <select
              value={draft.urgency}
              onChange={(e) => set("urgency", e.target.value)}
            >
              {["normal", "urgent", "hot"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Visibility">
            <select
              value={draft.status}
              onChange={(e) => set("status", e.target.value)}
            >
              <option value="active">{t("Draft")}</option>
              <option value="open">{t("Open for applications")}</option>
            </select>
          </Field>
        </div>
        <ErrorNotice error={save.error} />
        <div className="actions">
          <Link className="button secondary" to="/employer">
            {t("Cancel")}
          </Link>
          <Button type="submit" busy={save.isPending}>
            {t("Save opportunity")}
            <ArrowUpRight size={17} />
          </Button>
        </div>
      </form>
    </>
  );
}
const transitions: Record<string, string[]> = {
  submitted: ["viewed", "shortlisted", "rejected"],
  viewed: ["shortlisted", "rejected"],
  shortlisted: ["contacted", "rejected"],
  contacted: ["hired"],
};
export function Applicants() {
  const { id } = useParams();
  const { t } = useTranslation();
  const list = useInfiniteQuery({
    queryKey: ["applicants", id],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      api<Schema["ApplicationsPage"]>(
        `/jobs/${id}/applications?${query({ limit: 20, cursor: pageParam })}`,
      ),
    getNextPageParam: (p) => p.next_cursor ?? undefined,
  });
  const update = useAction(
    ({ id, status }: { id: number; status: string }) =>
      patch(`/applications/${id}/status`, { status }),
    ["applicants", "employer-jobs"],
  );
  return (
    <>
      <PageTitle
        eyebrow="MEET THE PERSON, NOT THE PAPER"
        title="Your next teammate could be here."
        action={
          <Link className="button secondary" to="/employer">
            {t("Employer studio")}
          </Link>
        }
      />
      <section className="panel">
        <ErrorNotice error={list.error || update.error} />
        {update.isSuccess && (
          <Success>{t("Application status updated.")}</Success>
        )}
        {list.isPending && <Loading />}
        {list.data?.pages
          .flatMap((p) => p.items)
          .map((a) => (
            <article className="applicant-row" key={a.id}>
              <div className="grow">
                <CandidateIdentity id={a.applicant_id} />
                <p>{a.cover_note || t("No cover note provided.")}</p>
                <small className="muted">
                  {dateLabel(a.applied_at)} · {t("Introduction")} #
                  {a.intro_video_id}
                </small>
                <ApplicationVideo id={a.id} />
              </div>
              <Badge>{t(a.status)}</Badge>
              {transitions[a.status] && (
                <select
                  aria-label={`${t("Update candidate")} ${a.applicant_id}`}
                  value=""
                  disabled={update.isPending}
                  onChange={(e) =>
                    update.mutate({ id: a.id, status: e.target.value })
                  }
                >
                  <option value="">{t("Next step…")}</option>
                  {transitions[a.status].map((s) => (
                    <option key={s} value={s}>
                      {t(s)}
                    </option>
                  ))}
                </select>
              )}
              {a.conversation_id && (
                <Link
                  className="button secondary small"
                  to={`/chat/${a.conversation_id}`}
                >
                  {t("Message")}
                </Link>
              )}
            </article>
          ))}
        {!list.isPending && !list.data?.pages[0].items.length && (
          <Empty title="Good people are on their way">
            {t("Applications for this opportunity will appear here.")}
          </Empty>
        )}
        {list.hasNextPage && (
          <Button
            busy={list.isFetchingNextPage}
            onClick={() => void list.fetchNextPage()}
          >
            {t("Load more")}
          </Button>
        )}
      </section>
    </>
  );
}

function CandidateIdentity({ id }: { id: number }) {
  const profile = useQuery({
    queryKey: ["public-profile", String(id)],
    queryFn: () =>
      api<{ first_name?: string; last_name?: string; position?: string }>(
        `/users/${id}/profile`,
      ),
  });
  const name = [profile.data?.first_name, profile.data?.last_name]
    .filter(Boolean)
    .join(" ");
  return (
    <Link className="text-link" to={`/users/${id}`}>
      {name || `Candidate #${id}`}
      <ArrowUpRight size={15} />
    </Link>
  );
}

function ApplicationVideo({ id }: { id: number }) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation();
  const video = useQuery({
    queryKey: ["application-video", id],
    queryFn: () => api<{ signed_url: string }>(`/applications/${id}/video`),
    enabled: open,
    staleTime: 120000,
    refetchInterval: open ? 120000 : false,
  });
  return (
    <div className="applicant-intro">
      <button
        className="text-link"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Play size={14} />
        {t(open ? "Hide introduction" : "Watch introduction")}
      </button>
      {open && (
        <>
          <ErrorNotice error={video.error} />
          {video.isPending ? (
            <Loading />
          ) : (
            video.data && (
              <video
                className="applicant-video"
                controls
                preload="metadata"
                src={video.data.signed_url}
              />
            )
          )}
        </>
      )}
    </div>
  );
}
