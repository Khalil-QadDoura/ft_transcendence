import "../../i18n";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { Modal } from "../../components/Modal";
import { ApiError, queryKeys } from "../../api/client";
import { profileApi } from "../profile/api";
import { peopleApi, userId } from "./api";
import "./people.css";

export function PublicProfile() {
  const { id } = useParams();
  const parsed = userId.safeParse(id);
  const value = parsed.success ? parsed.data : 0;
  return <PersonView key={value} id={value} />;
}
function PersonView({ id }: { id: number }) {
  const { t } = useTranslation("people");
  const cache = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const me = useQuery({
    queryKey: queryKeys.auth.me,
    queryFn: ({ signal }) => profileApi.get(signal),
  });
  const profile = useQuery({
    queryKey: ["people", id],
    queryFn: ({ signal }) => peopleApi.profile(id, signal),
    enabled: id > 0 && !!me.data && me.data.id !== id,
    retry: false,
  });
  if (me.data?.id === id) return <Navigate to="/profile" replace />;
  if (
    !id ||
    (profile.error instanceof ApiError && profile.error.status === 404)
  )
    return (
      <section className="people-page">
        <h1>{t("notFound")}</h1>
      </section>
    );
  if (me.isError || profile.isError)
    return (
      <section className="people-page">
        <p role="alert">{t("loadError")}</p>
        <Button
          onClick={() => void (me.isError ? me.refetch() : profile.refetch())}
        >
          {t("retry")}
        </Button>
      </section>
    );
  if (!profile.data)
    return (
      <section className="people-page" aria-busy="true">
        <p role="status">{t("loading")}</p>
        <div className="people-skeleton" />
      </section>
    );
  const person = profile.data;
  const name =
    [person.first_name, person.last_name].filter(Boolean).join(" ") ||
    t("member");
  async function perform(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
      setConfirm(false);
    } catch (cause) {
      setError(
        t(
          cause instanceof ApiError && cause.status === 409
            ? "changed"
            : "actionError",
        ),
      );
    } finally {
      // Another tab may have changed the relationship, or the response may have
      // been lost after the server committed. Reconcile even after a failed request.
      await Promise.all([
        cache.invalidateQueries({ queryKey: ["people"] }),
        cache.invalidateQueries({ queryKey: ["friends"] }),
      ]);
      setBusy(false);
    }
  }
  const relation = person.friendship_id;
  return (
    <section className="people-page">
      <div className="people-cover" aria-hidden="true" />
      <article className="people-card">
        <Avatar src={person.avatar_url} alt={name} size="xl" />
        <p className="people-presence">
          <span
            className={person.is_online ? "online-dot" : "offline-dot"}
            aria-hidden="true"
          />
          {t(person.is_online ? "online" : "offline")}
        </p>
        <h1>{name}</h1>
        <p className="people-position">{person.position || t("noPosition")}</p>
        <p className="people-bio">{person.bio || t("noBio")}</p>
        <div className="people-actions">
          {person.friendship_status === null && (
            <Button
              disabled={busy}
              onClick={() => void perform(() => peopleApi.add(id))}
            >
              {t("add")}
            </Button>
          )}
          {person.friendship_status === "pending_sent" && (
            <p role="status">{t("sent")}</p>
          )}
          {person.friendship_status === "pending_received" && (
            <>
              <Button
                disabled={busy || !relation}
                onClick={() => void perform(() => peopleApi.accept(relation!))}
              >
                {t("accept")}
              </Button>
              <Button
                variant="outline"
                disabled={busy || !relation}
                onClick={() => void perform(() => peopleApi.decline(relation!))}
              >
                {t("decline")}
              </Button>
            </>
          )}
          {person.friendship_status === "accepted" && (
            <Button
              variant="outline"
              disabled={busy || !relation}
              onClick={() => {
                setError("");
                setConfirm(true);
              }}
            >
              {t("remove")}
            </Button>
          )}
          <Button
            variant="lime"
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                const chat = await peopleApi.message(id);
                navigate(`/chat/${chat.id}`);
              })
            }
          >
            {t("message")}
          </Button>
        </div>
        {person.friendship_status &&
          person.friendship_status !== "pending_sent" &&
          !relation && <p role="status">{t("unavailable")}</p>}
        {error && !confirm && <p role="alert">{error}</p>}
      </article>
      <Modal
        isOpen={confirm}
        onClose={() => {
          if (!busy) setConfirm(false);
        }}
        title={t("removeTitle")}
        description={t("removeHint")}
      >
        {error && <p role="alert">{error}</p>}
        <div className="people-actions">
          <Button
            disabled={busy}
            onClick={() => void perform(() => peopleApi.remove(relation!))}
          >
            {t("remove")}
          </Button>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => setConfirm(false)}
          >
            {t("cancel")}
          </Button>
        </div>
      </Modal>
    </section>
  );
}
