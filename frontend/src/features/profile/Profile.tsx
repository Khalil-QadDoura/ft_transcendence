import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ArrowUpRight, Check, Mail, UserPlus, Video } from "lucide-react";
import { useState } from "react";
import {
  api,
  logout,
  patch,
  post,
  remove,
  type Conversation,
  type Schema,
  type User,
  uploadFile,
} from "../../api/client";
import { useAuth } from "../../app/state";
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
  useAction,
} from "../../components/ui";
import { credentials, profileSchema } from "../auth/schemas";

export function Profile() {
  const { user, loading, error } = useAuth();
  const { t } = useTranslation();
  if (loading) return <Loading />;
  if (!user)
    return (
      <ErrorNotice error={error || new Error(t("Please sign in again."))} />
    );
  return <ProfileForm key={user.id} user={user} />;
}
function ProfileForm({ user }: { user: User }) {
  const { t } = useTranslation();
  const [progress, setProgress] = useState<number | null>(null);
  const form = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      first_name: user.first_name || "",
      last_name: user.last_name || "",
      position: user.position || "",
      birth_date: user.birth_date || "",
      bio: user.bio || "",
    },
  });
  const save = useAction(
    (data: z.infer<typeof profileSchema>) => patch("/users/me", data),
    ["me"],
  );
  const upload = useAction(
    async (file: File) => {
      if (
        !["image/jpeg", "image/png", "image/webp"].includes(file.type) ||
        file.size > 5 * 1024 * 1024
      )
        throw new Error(t("Use a JPG, PNG, or WebP image smaller than 5 MB."));
      setProgress(0);
      const ext = file.type === "image/jpeg" ? "jpg" : file.type.split("/")[1];
      const signed = await post<{ object_key: string; put_url: string }>(
        `/media/avatar/upload-url?ext=${ext}`,
      );
      await uploadFile(signed.put_url, file, setProgress);
      await post("/media/avatar/confirm", { object_key: signed.object_key });
      setProgress(null);
    },
    ["me"],
  );
  return (
    <>
      <PageTitle
        eyebrow="THE PERSON BEHIND THE PROFILE"
        title="A little more you."
        description="Show the world what you bring to the table."
      />
      <div className="profile-layout">
        <aside className="panel profile-summary">
          <Avatar
            name={`${user.first_name || "Your"} ${user.last_name || "name"}`}
            size="xl"
            url={(user as User & { avatar_url?: string }).avatar_url}
          />
          <h2>
            {[user.first_name, user.last_name].filter(Boolean).join(" ") ||
              t("Your name belongs here")}
          </h2>
          <p>{user.position || t("Your next role is waiting")}</p>
          <Badge>
            <Check size={13} />
            {t(
              user.is_email_verified ? "Email verified" : "Email not verified",
            )}
          </Badge>
          <hr />
          <span className="email-line">
            <Mail size={15} />
            {user.email}
          </span>
          <label className="button secondary full upload-label">
            {t("Upload avatar")}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={upload.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
              }}
            />
          </label>
          {progress !== null && (
            <progress
              value={progress}
              max={100}
              aria-label={t("Upload progress")}
            />
          )}
          <ErrorNotice error={upload.error} />
          {upload.isSuccess && <Success>{t("Avatar uploaded.")}</Success>}
          <Link className="text-link" to={`/users/${user.id}`}>
            {t("View public profile")}
            <ArrowUpRight size={16} />
          </Link>
        </aside>
        <section className="panel">
          <h2>{t("Tell your story")}</h2>
          <p className="muted">{t("Keep it honest. Keep it you.")}</p>
          <form
            onSubmit={form.handleSubmit((data) => save.mutate(data))}
            className="profile-form"
            noValidate
          >
            <div className="form-grid">
              <Field
                label="First name"
                error={form.formState.errors.first_name?.message}
              >
                <input
                  autoComplete="given-name"
                  {...form.register("first_name")}
                />
              </Field>
              <Field
                label="Last name"
                error={form.formState.errors.last_name?.message}
              >
                <input
                  autoComplete="family-name"
                  {...form.register("last_name")}
                />
              </Field>
            </div>
            <Field
              label="Professional headline"
              error={form.formState.errors.position?.message}
            >
              <input
                placeholder={t("What do you love to do?")}
                {...form.register("position")}
              />
            </Field>
            <Field
              label="Date of birth"
              hint="You must be at least 18 years old."
              error={form.formState.errors.birth_date?.message}
            >
              <input
                type="date"
                autoComplete="bday"
                {...form.register("birth_date")}
              />
            </Field>
            <Field
              label="About you"
              hint="500 characters maximum"
              error={form.formState.errors.bio?.message}
            >
              <textarea
                rows={5}
                maxLength={500}
                {...form.register("bio")}
                placeholder={t(
                  "A little about your experience, your passions, and what comes next.",
                )}
              />
            </Field>
            <ErrorNotice error={save.error} />
            {save.isSuccess && (
              <Success>{t("Profile updated. Looking good.")}</Success>
            )}
            <Button type="submit" busy={save.isPending}>
              {t("Save my profile")}
              <Check size={17} />
            </Button>
          </form>
        </section>
      </div>
    </>
  );
}
export function PublicProfile() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const profile = useQuery({
    queryKey: ["public-profile", id],
    queryFn: () => api<Schema["PublicProfileOut"]>(`/users/${id}/profile`),
  });
  const add = useAction(
    () => post("/friends/requests", { addressee_id: Number(id) }),
    ["public-profile", "friends"],
  );
  const message = useAction(async () => {
    const conversation = await post<Conversation>("/conversations", {
      type: "direct",
      peer_user_id: Number(id),
    });
    navigate(`/chat/${conversation.id}`);
  });
  if (profile.isPending) return <Loading />;
  if (!profile.data) return <ErrorNotice error={profile.error} />;
  const p = profile.data;
  return (
    <>
      <PageTitle
        eyebrow="GOOD PEOPLE. REAL CONNECTIONS."
        title="Meet your network."
      />
      <section className="public-profile panel">
        <div className="public-cover">
          <span>✳</span>
          <span>YOU BELONG HERE.</span>
        </div>
        <div className="public-profile-body">
          <Avatar
            name={`${p.first_name || "WOZU"} ${p.last_name || "member"}`}
            size="xl"
          />
          <Badge tone={p.is_online ? "" : "neutral"}>
            {t(p.is_online ? "Online now" : "Offline")}
          </Badge>
          <h1>
            {p.first_name} {p.last_name}
          </h1>
          <h3>{p.position}</h3>
          <p className="preserve-lines">
            {p.bio || t("Every great story starts somewhere.")}
          </p>
          <ErrorNotice error={add.error || message.error} />
          {Number(id) !== user?.id && (
            <div className="actions">
              {!p.friendship_status && (
                <Button busy={add.isPending} onClick={() => add.mutate()}>
                  <UserPlus size={17} />
                  {t("Connect")}
                </Button>
              )}
              {p.friendship_status && (
                <Badge>{t(p.friendship_status.replaceAll("_", " "))}</Badge>
              )}
              <Button
                variant="secondary"
                busy={message.isPending}
                onClick={() => message.mutate()}
              >
                <Mail size={17} />
                {t("Send a message")}
              </Button>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
export function Friends() {
  const { t } = useTranslation();
  const [peer, setPeer] = useState("");
  const navigate = useNavigate();
  const friends = useQuery({
    queryKey: ["friends"],
    queryFn: () => api<Schema["FriendOut"][]>("/friends"),
    refetchInterval: 30000,
  });
  const requests = useQuery({
    queryKey: ["friend-requests"],
    queryFn: () => api<Schema["FriendshipOut"][]>("/friends/requests"),
  });
  const respond = useAction(
    ({ id, action }: { id: number; action: string }) =>
      post(`/friends/requests/${id}/${action}`),
    ["friends", "friend-requests"],
  );
  return (
    <>
      <PageTitle
        eyebrow="BETTER, TOGETHER"
        title="Your people are out there."
        description="Start a conversation. Make a connection. Grow together."
      />
      <form
        className="panel inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (Number(peer) > 0) navigate(`/users/${peer}`);
        }}
      >
        <Field label="Find a person by user ID">
          <input
            type="number"
            min="1"
            required
            value={peer}
            onChange={(e) => setPeer(e.target.value)}
            placeholder="123"
          />
        </Field>
        <Button type="submit">
          {t("View profile")}
          <ArrowUpRight size={17} />
        </Button>
      </form>
      <ErrorNotice error={friends.error || requests.error || respond.error} />
      {!!requests.data?.length && (
        <section className="panel">
          <h2>{t("New connections")}</h2>
          {requests.data.map((r) => (
            <div className="application-row" key={r.id}>
              <Avatar name={String(r.requester_id)} />
              <Link className="grow" to={`/users/${r.requester_id}`}>
                {t("View profile")} #{r.requester_id}
              </Link>
              <Button
                busy={respond.isPending}
                onClick={() => respond.mutate({ id: r.id, action: "accept" })}
              >
                {t("Accept")}
              </Button>
              <Button
                variant="secondary"
                busy={respond.isPending}
                onClick={() => respond.mutate({ id: r.id, action: "decline" })}
              >
                {t("Decline")}
              </Button>
            </div>
          ))}
        </section>
      )}
      <div className="people-grid">
        {friends.data?.map((f) => (
          <Link
            to={`/users/${f.user_id}`}
            className="panel person-card"
            key={f.user_id}
          >
            <Avatar
              name={`${f.first_name || "W"} ${f.last_name || ""}`}
              size="large"
            />
            <Badge tone={f.is_online ? "" : "neutral"}>
              {t(f.is_online ? "Online now" : "Offline")}
            </Badge>
            <h3>
              {f.first_name} {f.last_name}
            </h3>
            <p>{f.position}</p>
            <span className="text-link">
              {t("View profile")}
              <ArrowUpRight size={16} />
            </span>
          </Link>
        ))}
      </div>
      {friends.isPending ? (
        <Loading />
      ) : (
        !friends.data?.length && (
          <Empty title="Good connections start with hello">
            {t("Find a person by their user ID to send a connection request.")}
          </Empty>
        )
      )}
    </>
  );
}
export function Settings() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const schema = z.object({
    current_password: z.string().min(1, "This field is required."),
    new_password: credentials.shape.password,
  });
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
  });
  const change = useAction(async (data: z.infer<typeof schema>) => {
    await post("/auth/change-password", data);
    await logout();
    navigate("/login");
  });
  return (
    <>
      <PageTitle
        eyebrow="MAKE YOURSELF AT HOME"
        title="Your account, your way."
      />
      <section className="panel narrow-panel">
        <h2>{t("Change password")}</h2>
        <form onSubmit={form.handleSubmit((data) => change.mutate(data))}>
          <Field
            label="Current password"
            error={form.formState.errors.current_password?.message}
          >
            <input
              type="password"
              autoComplete="current-password"
              {...form.register("current_password")}
            />
          </Field>
          <Field
            label="New password"
            error={form.formState.errors.new_password?.message}
          >
            <input
              type="password"
              autoComplete="new-password"
              {...form.register("new_password")}
            />
          </Field>
          <ErrorNotice error={change.error} />
          <Button type="submit" busy={change.isPending}>
            {t("Update password")}
          </Button>
        </form>
      </section>
      <section className="panel narrow-panel">
        <h2>{t("Your video introduction")}</h2>
        <p>{t("Update your introduction as your story grows.")}</p>
        <Link className="button secondary" to="/videos">
          <Video size={17} />
          {t("Visit video studio")}
        </Link>
      </section>
      <section className="panel narrow-panel danger-zone">
        <h2>{t("Delete account")}</h2>
        <p>
          {t("Your account will be deactivated and you will be signed out.")}
        </p>
        <Confirm
          title="Delete your account?"
          description="This deactivates your account. You will lose access to your profile and conversations."
          danger
          onConfirm={async () => {
            await remove("/users/me");
            await logout();
            navigate("/login");
          }}
        >
          {t("Delete my account")}
        </Confirm>
      </section>
    </>
  );
}
