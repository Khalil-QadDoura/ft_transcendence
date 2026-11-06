import { useEffect, useState } from "react";
import { useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Bookmark,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  Clock3,
  Compass,
  MapPin,
  Search,
  SlidersHorizontal,
  Sparkles,
  Video,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  api,
  ApiError,
  post,
  query,
  type Job,
  type Schema,
} from "../../api/client";
import { SignalArtwork } from "../../components/SignalArtwork";
import { useAuth, useSavedJobs } from "../../app/state";
import {
  Avatar,
  Badge,
  Button,
  Confirm,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  PageTitle,
  Success,
  TextLink,
  dateLabel,
  money,
  useAction,
} from "../../components/ui";

export function HeroArtwork() {
  return <SignalArtwork />;
}
function JobCard({
  job,
  saved,
  toggle,
}: {
  job: Job;
  saved: boolean;
  toggle: (id: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <article className="job-card">
      <div className="job-card-top">
        <span className={`company-mark color-${job.id % 5}`}>
          {(job.company_name || "W").slice(0, 1)}
        </span>
        <div className="job-company">
          <strong>{job.company_name || t("Independent employer")}</strong>
          <span>
            <MapPin size={12} />
            {job.location}
          </span>
        </div>
        <button
          className={`icon-button save-button ${saved ? "saved" : ""}`}
          aria-label={t(saved ? "Unsave job" : "Save job")}
          aria-pressed={saved}
          onClick={() => toggle(job.id)}
        >
          <Bookmark size={19} fill={saved ? "currentColor" : "none"} />
        </button>
      </div>
      <Link className="job-title" to={`/jobs/${job.id}`}>
        <h3>{job.title}</h3>
      </Link>
      <div className="job-tags">
        <Badge>{t(job.schedule.replaceAll("_", " "))}</Badge>
        {job.urgency !== "normal" && (
          <Badge tone="orange">{t("Actively hiring")}</Badge>
        )}
        <Badge tone="neutral">{t("Video application")}</Badge>
      </div>
      <p className="job-excerpt">{job.description}</p>
      <div className="job-card-footer">
        <div>
          <strong>
            {money(job.salary_amount, job.salary_currency) ||
              t("Salary on request")}
          </strong>
          {job.salary_amount != null && <span> / {t(job.salary_type)}</span>}
          <small>
            <Clock3 size={12} />
            {dateLabel(job.created_at)}
          </small>
        </div>
        <Link
          className="job-go"
          to={`/jobs/${job.id}`}
          aria-label={`${t("View job")}: ${job.title}`}
        >
          <ArrowUpRight size={20} />
        </Link>
      </div>
    </article>
  );
}
export function Jobs() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const { saved, toggle } = useSavedJobs();
  const [search, setSearch] = useState(params.get("keyword") || "");
  const [filters, setFilters] = useState(false);
  const [tab, setTab] = useState("all");
  const filterKey = params.toString();
  const jobs = useInfiniteQuery({
    queryKey: ["jobs", filterKey],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      api<Schema["JobsPage"]>(
        `/jobs/open?${filterKey}&${query({ limit: 12, cursor: pageParam })}`,
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const savedQueries = useQueries({
    queries: saved.map((id) => ({
      queryKey: ["job", String(id)],
      queryFn: () => api<Job>(`/jobs/${id}`),
      enabled: tab === "saved",
      retry: false,
    })),
  });
  const all = jobs.data?.pages.flatMap((p) => p.items) || [];
  const items =
    tab === "saved"
      ? savedQueries.flatMap((q) => (q.data ? [q.data] : []))
      : all;
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };
  const profileProgress = user
    ? [
        user.first_name,
        user.last_name,
        user.position,
        user.birth_date,
        user.bio,
      ].filter(Boolean).length * 20
    : 0;
  return (
    <>
      <div className="welcome-line">
        <span>
          {t(
            user?.first_name
              ? "Good things are ahead"
              : "A fresh start looks good on you",
          )}
          {user?.first_name ? `, ${user.first_name}.` : "."}{" "}
          <span className="sun-glyph">✳</span>
        </span>
        <span className="date-stamp">
          {new Intl.DateTimeFormat(undefined, {
            month: "long",
            day: "numeric",
            year: "numeric",
          }).format(new Date())}
        </span>
      </div>
      <section className="discovery-hero">
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="tiny-dot" />
            {t("OPPORTUNITY, WITH PERSONALITY")}
          </span>
          <h1>
            {t("Your next chapter.")}
            <br />
            <em>{t("Make it yours.")}</em>
          </h1>
          <p>
            {t("Find work that feels like you. Meet the people behind it.")}
          </p>
          <a href="#opportunities" className="hero-link">
            {t("Explore opportunities")}
            <ArrowDown size={17} />
          </a>
        </div>
        <HeroArtwork />
      </section>
      <form
        className="search-bar"
        onSubmit={(e) => {
          e.preventDefault();
          setFilter("keyword", search);
        }}
      >
        <Search size={21} />
        <input
          aria-label={t("Search jobs")}
          placeholder={t("Job title, skill, or your next big thing…")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="search-divider" />
        <label className="search-schedule">
          <BriefcaseBusiness size={18} />
          <select
            aria-label={t("Work schedule")}
            value={params.get("schedule") || ""}
            onChange={(e) => setFilter("schedule", e.target.value)}
          >
            <option value="">{t("Any schedule")}</option>
            <option value="full_time">{t("full time")}</option>
            <option value="part_time">{t("part time")}</option>
            <option value="internship">{t("internship")}</option>
          </select>
        </label>
        <Button type="submit">
          {t("Find my next role")}
          <ArrowRight size={17} />
        </Button>
      </form>
      <div className="discovery-grid">
        <section id="opportunities" className="opportunities">
          <div className="section-heading">
            <div>
              <span className="eyebrow">{t("A WORLD OF POSSIBILITIES")}</span>
              <h2>
                {t("Find your kind of work")}
                <span className="heading-dot">.</span>
              </h2>
            </div>
            <button
              className={`filter-button ${filters ? "selected" : ""}`}
              onClick={() => setFilters(!filters)}
              aria-expanded={filters}
            >
              <SlidersHorizontal size={16} />
              {t("Filters")}
              {params.size > 0 && <span>{params.size}</span>}
            </button>
          </div>
          {filters && (
            <div className="filter-panel">
              <Field label="Minimum salary">
                <input
                  type="number"
                  min="0"
                  value={params.get("salary_min") || ""}
                  onChange={(e) => setFilter("salary_min", e.target.value)}
                />
              </Field>
              <Field label="Maximum salary">
                <input
                  type="number"
                  min="0"
                  value={params.get("salary_max") || ""}
                  onChange={(e) => setFilter("salary_max", e.target.value)}
                />
              </Field>
              <Field label="Urgency">
                <select
                  value={params.get("urgency") || ""}
                  onChange={(e) => setFilter("urgency", e.target.value)}
                >
                  <option value="">{t("Any")}</option>
                  {["normal", "urgent", "hot"].map((v) => (
                    <option key={v} value={v}>
                      {t(v)}
                    </option>
                  ))}
                </select>
              </Field>
              <Button
                variant="ghost"
                onClick={() => {
                  setParams({});
                  setSearch("");
                }}
              >
                {t("Clear filters")}
              </Button>
            </div>
          )}
          <div className="results-bar">
            <div className="tabs">
              <button
                className={tab === "all" ? "selected" : ""}
                onClick={() => setTab("all")}
              >
                {t("All opportunities")}
                <span>
                  {all.length}
                  {jobs.hasNextPage ? "+" : ""}
                </span>
              </button>
              <button
                className={tab === "saved" ? "selected" : ""}
                onClick={() => setTab("saved")}
              >
                <Bookmark size={14} />
                {t("Saved")}
                <span>{saved.length}</span>
              </button>
            </div>
            <span className="muted result-order">{t("Newest first")}</span>
          </div>
          {tab === "saved" && (
            <p className="muted small-text">
              {t("Saved on this device. Unavailable jobs are omitted.")}
            </p>
          )}
          <ErrorNotice
            error={
              tab === "all"
                ? jobs.error
                : savedQueries.find((q) => q.error)?.error
            }
            retry={() => void jobs.refetch()}
          />
          {jobs.isPending && tab === "all" ? (
            <div className="job-grid" aria-label={t("Loading…")}>
              {[1, 2, 3, 4].map((i) => (
                <div className="job-skeleton" key={i}>
                  <i />
                  <i />
                  <i />
                </div>
              ))}
            </div>
          ) : (
            <div className="job-grid">
              {items.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  saved={saved.includes(job.id)}
                  toggle={toggle}
                />
              ))}
            </div>
          )}
          {!jobs.isPending && !jobs.error && items.length === 0 && (
            <Empty
              title={
                tab === "saved"
                  ? "Your shortlist starts here"
                  : "No matching opportunities"
              }
            >
              {t(
                tab === "saved"
                  ? "Save a role that catches your eye and find it here."
                  : "Try a different keyword or clear your filters.",
              )}
            </Empty>
          )}
          {jobs.hasNextPage && tab === "all" && (
            <Button
              className="load-more"
              variant="secondary"
              busy={jobs.isFetchingNextPage}
              onClick={() => void jobs.fetchNextPage()}
            >
              {t("More opportunities")}
              <ArrowDown size={16} />
            </Button>
          )}
        </section>
        <aside className="discovery-aside">
          <section className="profile-card">
            <div className="aside-heading">
              <span className="eyebrow">{t("YOUR STORY STARTS HERE")}</span>
              <Sparkles size={17} />
            </div>
            <div
              className="profile-ring"
              style={
                { "--progress": `${profileProgress}%` } as React.CSSProperties
              }
            >
              <Avatar
                name={
                  user?.first_name
                    ? `${user.first_name} ${user.last_name}`
                    : "You"
                }
                size="large"
              />
            </div>
            <h3>
              {user?.first_name
                ? `${user.first_name}, meet your future.`
                : t("Good work starts with you.")}
            </h3>
            <p>
              {t(
                "A complete profile helps the right people find the real you.",
              )}
            </p>
            <div className="progress-caption">
              <span>{t("Profile strength")}</span>
              <strong>{profileProgress}%</strong>
            </div>
            <div className="progress-track">
              <span style={{ width: `${profileProgress}%` }} />
            </div>
            <Link
              className="button secondary full"
              to={user ? "/profile" : "/register"}
            >
              {t(user ? "Complete my profile" : "Create my profile")}
              <ArrowUpRight size={16} />
            </Link>
          </section>
          <Link to="/videos" className="video-promo">
            <span className="eyebrow">{t("LESS PAPER. MORE YOU.")}</span>
            <div className="video-promo-art">
              <span className="video-orbit" />
              <Video size={44} />
              <span className="video-duration">30s</span>
            </div>
            <h3>{t("A hello goes a long way.")}</h3>
            <p>
              {t(
                "Introduce yourself in 30 seconds. Let your next team meet you.",
              )}
            </p>
            <span className="text-link">
              {t("Step into the studio")}
              <ArrowUpRight size={16} />
            </span>
          </Link>
          <Link to="/game" className="play-promo">
            <span className="play-symbol">✳</span>
            <div>
              <strong>{t("Take a curious little break.")}</strong>
              <span>{t("Human or AI? Play Turing Duel.")}</span>
            </div>
            <ChevronRight size={18} />
          </Link>
          <div className="aside-note">
            <Compass size={18} />
            <p>{t("The best opportunities start with a little curiosity.")}</p>
          </div>
        </aside>
      </div>
    </>
  );
}
export function JobDetail() {
  const { id } = useParams();
  useEffect(() => {
    if (id) void post(`/jobs/${id}/view`).catch(() => {});
  }, [id]);
  const { user, signedIn } = useAuth();
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const job = useQuery({
    queryKey: ["job", id],
    queryFn: () => api<Job>(`/jobs/${id}`),
  });
  const apply = useAction(
    () => post(`/jobs/${id}/apply`, { cover_note: note || null }),
    ["applications"],
  );
  if (job.isPending) return <Loading />;
  if (job.error || !job.data) return <ErrorNotice error={job.error} />;
  const j = job.data;
  return (
    <>
      <Link className="back-link" to="/jobs">
        ← {t("All opportunities")}
      </Link>
      <section className="detail-hero">
        <div className={`company-mark large color-${j.id % 5}`}>
          {(j.company_name || "W")[0]}
        </div>
        <span className="eyebrow">{j.company_name}</span>
        <h1>{j.title}</h1>
        <div className="detail-meta">
          <span>
            <MapPin size={17} />
            {j.location}
          </span>
          <span>
            <BriefcaseBusiness size={17} />
            {t(j.schedule.replaceAll("_", " "))}
          </span>
          <span>
            <Clock3 size={17} />
            {dateLabel(j.created_at)}
          </span>
        </div>
      </section>
      <div className="detail-grid">
        <section className="panel prose">
          <h2>{t("About this opportunity")}</h2>
          <p className="preserve-lines">{j.description}</p>
          <h3>{t("Make your introduction count")}</h3>
          <p>
            {t(
              "A complete profile and a published video introduction are required to apply. Your story matters as much as your experience.",
            )}
          </p>
          <TextLink to="/videos">{t("Visit video studio")}</TextLink>
        </section>
        <aside className="panel apply-panel">
          <span className="eyebrow">{t("YOUR NEXT MOVE")}</span>
          <h2>
            {money(j.salary_amount, j.salary_currency) || t("Let’s talk")}
          </h2>
          <p>
            {j.salary_amount != null
              ? t(j.salary_type)
              : t("Salary shared by the employer")}
          </p>
          <hr />
          <ErrorNotice error={apply.error} />
          {apply.error instanceof ApiError && apply.error.status === 422 && (
            <div className="actions">
              <TextLink to="/profile">{t("Complete my profile")}</TextLink>
              <TextLink to="/videos">{t("Visit video studio")}</TextLink>
            </div>
          )}
          {apply.isSuccess ? (
            <Success>
              {t("Application sent. Your next chapter is one step closer.")}
            </Success>
          ) : signedIn ? (
            user?.id === j.created_by_id ? (
              <TextLink to="/employer">{t("Manage this opportunity")}</TextLink>
            ) : j.status !== "open" ? (
              <Badge>{t("Applications are closed")}</Badge>
            ) : (
              <>
                <Field
                  label="A note to your future team"
                  hint="Optional · 1,000 characters maximum"
                >
                  <textarea
                    rows={5}
                    maxLength={1000}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder={t(
                      "Tell them why this feels like your next chapter.",
                    )}
                  />
                </Field>
                <Button
                  className="full"
                  busy={apply.isPending}
                  onClick={() => apply.mutate()}
                >
                  {t("Apply with my video")}
                  <ArrowUpRight size={17} />
                </Button>
                <p className="small-text muted">
                  {t(
                    "Your profile and published video will be shared with this employer.",
                  )}
                </p>
              </>
            )
          ) : (
            <Link
              className="button primary full"
              to={`/login?next=/jobs/${id}`}
            >
              {t("Sign in to apply")}
              <ArrowRight size={17} />
            </Link>
          )}
          <div className="application-checks">
            <span>
              <Check size={15} />
              {t("Be yourself")}
            </span>
            <span>
              <Check size={15} />
              {t("Make a real connection")}
            </span>
          </div>
        </aside>
      </div>
    </>
  );
}
export function Applications() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("");
  const applications = useInfiniteQuery({
    queryKey: ["applications", status],
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) =>
      api<Schema["ApplicationsPage"]>(
        `/applications/mine?${query({ status, cursor: pageParam, limit: 20 })}`,
      ),
    getNextPageParam: (p) => p.next_cursor ?? undefined,
  });
  const items = applications.data?.pages.flatMap((p) => p.items) || [];
  const clientAction = useAction(
    (id: number) => api(`/applications/${id}`, { method: "DELETE" }),
    ["applications"],
  );
  return (
    <>
      <PageTitle
        eyebrow="EVERY STEP IS A STEP FORWARD"
        title="Your next chapter, in progress."
        description="Keep your opportunities and conversations in one place."
      />
      <div className="panel">
        <div className="section-heading">
          <h2>{t("My applications")}</h2>
          <select
            aria-label={t("Application status")}
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">{t("All statuses")}</option>
            {[
              "submitted",
              "viewed",
              "shortlisted",
              "contacted",
              "hired",
              "rejected",
              "withdrawn",
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        <ErrorNotice error={applications.error || clientAction.error} />
        {applications.isPending && <Loading />}
        {items.map((app) => (
          <ApplicationRow
            key={app.id}
            application={app}
            onWithdraw={() => clientAction.mutateAsync(app.id)}
          />
        ))}
        {!applications.isPending && !items.length && (
          <Empty
            title="Your next opportunity is waiting"
            action={
              <Link className="button primary" to="/jobs">
                {t("Discover jobs")}
                <ArrowRight size={16} />
              </Link>
            }
          >
            {t("When you apply to a role, you can follow its progress here.")}
          </Empty>
        )}
        {applications.hasNextPage && (
          <Button
            variant="secondary"
            busy={applications.isFetchingNextPage}
            onClick={() => void applications.fetchNextPage()}
          >
            {t("Load more")}
          </Button>
        )}
      </div>
    </>
  );
}
function ApplicationRow({
  application: a,
  onWithdraw,
}: {
  application: Schema["ApplicationOut"];
  onWithdraw: () => Promise<unknown>;
}) {
  const { t } = useTranslation();
  const job = useQuery({
    queryKey: ["job", String(a.job_id)],
    queryFn: () => api<Job>(`/jobs/${a.job_id}`),
    retry: false,
  });
  return (
    <article className="application-row">
      <span className={`company-mark color-${a.job_id % 5}`}>
        {(job.data?.company_name || "W")[0]}
      </span>
      <div className="grow">
        <Link to={`/jobs/${a.job_id}`}>
          <h3>{job.data?.title || `${t("Opportunity")} #${a.job_id}`}</h3>
        </Link>
        <p>
          {job.data?.company_name} · {dateLabel(a.applied_at)}
        </p>
      </div>
      <Badge>{t(a.status)}</Badge>
      {a.conversation_id && (
        <Link
          className="button secondary small"
          to={`/chat/${a.conversation_id}`}
        >
          {t("Message")}
        </Link>
      )}
      {["submitted", "shortlisted"].includes(a.status) && (
        <Confirm
          title="Withdraw application?"
          description="You will no longer be considered for this opportunity."
          onConfirm={onWithdraw}
          danger
        >
          {t("Withdraw")}
        </Confirm>
      )}
    </article>
  );
}
