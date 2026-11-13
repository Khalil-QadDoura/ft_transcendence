import "../../i18n";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/Button";
import { Input } from "../../components/Input";
import { Avatar } from "../../components/Avatar";
import { Modal } from "../../components/Modal";
import { peopleApi, userId } from "./api";
import { friendsApi, type Friend, type FriendRequest } from "./friends";
import "./people.css";

export function FriendsPage() {
  const { t } = useTranslation("people");
  const [tab, setTab] = useState<"list" | "requests">("list");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [target, setTarget] = useState<Friend | null>(null);
  const [search, setSearch] = useState("");
  const navigate = useNavigate();
  const cache = useQueryClient();
  const list = useQuery({
    queryKey: ["friends", "list"],
    queryFn: ({ signal }) => friendsApi.list(signal),
    retry: false,
  });
  const requests = useQuery({
    queryKey: ["friends", "requests"],
    queryFn: ({ signal }) => friendsApi.requests(signal),
    retry: false,
  });
  async function change(
    kind: "list" | "requests",
    id: number,
    action: () => Promise<unknown>,
  ) {
    if (busy) return;
    setBusy(true);
    setError("");
    const key = ["friends", kind];
    await cache.cancelQueries({ queryKey: key });
    const before = cache.getQueryData<Friend[] | FriendRequest[]>(key);
    cache.setQueryData(
      key,
      before?.filter((row) =>
        "user_id" in row ? row.friendship_id !== id : row.id !== id,
      ),
    );
    try {
      await action();
      setTarget(null);
    } catch {
      cache.setQueryData(key, before);
      setError(t("actionError"));
    } finally {
      await cache.invalidateQueries({ queryKey: ["friends"] });
      await cache.invalidateQueries({ queryKey: ["people"] });
      setBusy(false);
    }
  }
  const active = tab === "list" ? list : requests;
  return (
    <section className="people-page">
      <header>
        <p className="eyebrow">{t("circle")}</p>
        <h1>{t("friendsTitle")}</h1>
        <p>{t("friendsHint")}</p>
      </header>
      <form
        className="people-actions"
        onSubmit={(event) => {
          event.preventDefault();
          const id = userId.safeParse(search);
          if (id.success) {
            setError("");
            navigate(`/users/${id.data}`);
          } else setError(t("invalidId"));
        }}
      >
        <Input
          label={t("profileId")}
          inputMode="numeric"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Button type="submit">{t("openProfile")}</Button>
      </form>
      <div
        className="people-actions"
        role="group"
        aria-label={t("friendsTitle")}
      >
        <Button aria-pressed={tab === "list"} onClick={() => setTab("list")}>
          {t("friendsTab")}
        </Button>
        <Button
          aria-pressed={tab === "requests"}
          onClick={() => setTab("requests")}
        >
          {t("requestsTab")}
        </Button>
      </div>
      {error && !target && <p role="alert">{error}</p>}
      {active.isPending ? (
        <div aria-busy="true">
          <p role="status">{t("loading")}</p>
          <div className="people-skeleton" />
        </div>
      ) : active.isError ? (
        <div role="alert">
          <p>{t("loadError")}</p>
          <Button onClick={() => void active.refetch()}>{t("retry")}</Button>
        </div>
      ) : (
        <>
          {!active.data?.length && (
            <div className="friends-empty">
              <h2>{t(tab === "list" ? "noFriends" : "noRequests")}</h2>
              <p>{t("emptyHint")}</p>
            </div>
          )}
          <ul className="friends-grid">
            {tab === "list"
              ? list.data?.map((friend) => {
                  const name =
                    [friend.first_name, friend.last_name]
                      .filter(Boolean)
                      .join(" ") || t("member");
                  return (
                    <li className="friend-card" key={friend.user_id}>
                      <Avatar src={friend.avatar_url} alt={name} size="lg" />
                      <h2>
                        <Link to={`/users/${friend.user_id}`}>{name}</Link>
                      </h2>
                      <p>{friend.position}</p>
                      <p className="people-presence">
                        <span
                          className={
                            friend.is_online ? "online-dot" : "offline-dot"
                          }
                          aria-hidden="true"
                        />
                        {t(friend.is_online ? "online" : "offline")}
                      </p>
                      <Button
                        variant="outline"
                        disabled={busy || !friend.friendship_id}
                        onClick={() => {
                          setError("");
                          setTarget(friend);
                        }}
                      >
                        {t("remove")}
                      </Button>
                      {!friend.friendship_id && <p>{t("unavailable")}</p>}
                    </li>
                  );
                })
              : requests.data?.map((request) => (
                  <li className="friend-card" key={request.id}>
                    <h2>
                      <Link to={`/users/${request.requester_id}`}>
                        {t("requestFrom", { id: request.requester_id })}
                      </Link>
                    </h2>
                    <div className="people-actions">
                      <Button
                        disabled={busy}
                        onClick={() =>
                          void change("requests", request.id, () =>
                            peopleApi.accept(request.id),
                          )
                        }
                      >
                        {t("accept")}
                      </Button>
                      <Button
                        disabled={busy}
                        variant="outline"
                        onClick={() =>
                          void change("requests", request.id, () =>
                            peopleApi.decline(request.id),
                          )
                        }
                      >
                        {t("decline")}
                      </Button>
                    </div>
                  </li>
                ))}
          </ul>
        </>
      )}
      <Modal
        isOpen={!!target}
        onClose={() => {
          if (!busy) setTarget(null);
        }}
        title={t("removeTitle")}
        description={t("removeHint")}
      >
        {error && <p role="alert">{error}</p>}
        <div className="people-actions">
          <Button
            disabled={busy}
            onClick={() => {
              if (target?.friendship_id)
                void change("list", target.friendship_id, () =>
                  peopleApi.remove(target.friendship_id!),
                );
            }}
          >
            {t("remove")}
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
