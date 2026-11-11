import "../../i18n";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, type FieldError } from "react-hook-form";
import { Avatar } from "../../components/Avatar";
import { Input } from "../../components/Input";
import { Textarea } from "../../components/Textarea";
import { Button } from "../../components/Button";
import { ApiError, queryKeys } from "../../api/client";
import { applyServerValidation } from "../../lib/server-validation";
import { createProfilePatchSchema } from "./schemas";
import {
  changedProfile,
  profileApi,
  profileFields,
  profileValues,
  type Profile,
  type ProfileValues,
  type ProfileField,
} from "./api";
import { avatarApi, avatarFileError } from "./avatar";
import "./profile.css";

function ProfilePhoto({
  profile,
  refresh,
}: {
  profile: Profile;
  refresh: () => Promise<unknown>;
}) {
  const { t } = useTranslation("profile");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => () => controller.current?.abort(), []);
  const reset = () => {
    setFile(null);
    setPreview("");
    if (input.current) input.current.value = "";
  };
  async function upload() {
    if (!file || busy) return;
    const pending = new AbortController();
    controller.current = pending;
    setBusy(true);
    setError("");
    setSaved(false);
    setProgress(0);
    try {
      await avatarApi.upload(file, pending.signal, setProgress);
      await refresh();
      if (!pending.signal.aborted) {
        reset();
        setSaved(true);
      }
    } catch (error) {
      if (!pending.signal.aborted) {
        if (error instanceof ApiError && error.status === 415) {
          reset();
          setError(t("photoInvalid"));
        } else setError(t("photoError"));
      }
    } finally {
      if (!pending.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="profile-photo" aria-labelledby="photo-title">
      <h2 id="photo-title">{t("photo")}</h2>
      <Avatar
        key={profile.avatar_url}
        src={profile.avatar_url}
        alt={
          `${profile.first_name ?? ""} ${profile.last_name ?? ""}`.trim() ||
          t("newMember")
        }
        size="xl"
      />
      {file && preview && (
        <img className="profile-preview" src={preview} alt={t("preview")} />
      )}
      <p>{t("photoHint")}</p>
      {profile.avatar_url === undefined ? (
        <p>{t("photoUnavailable")}</p>
      ) : (
        <>
          <input
            ref={input}
            className="sr-only"
            type="file"
            id="profile-photo"
            aria-label={t("choose")}
            accept="image/jpeg,image/png,image/webp"
            disabled={busy}
            onChange={(event) => {
              const next = event.target.files?.[0];
              setSaved(false);
              setError("");
              reset();
              if (!next) return;
              const invalid = avatarFileError(next);
              if (invalid)
                setError(t(invalid === "type" ? "photoType" : "photoSize"));
              else setFile(next);
            }}
          />
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            {t("choose")}
          </Button>
          {file && (
            <div className="profile-photo-actions">
              <Button isLoading={busy} onClick={() => void upload()}>
                {t(busy ? "uploading" : "upload")}
              </Button>
              <Button variant="ghost" disabled={busy} onClick={reset}>
                {t("removePreview")}
              </Button>
            </div>
          )}
          {busy && (
            <progress aria-label={t("progress")} max="100" value={progress} />
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {saved && <p role="status">{t("photoSaved")}</p>}
    </section>
  );
}

function ProfileEditor({ profile }: { profile: Profile }) {
  const { t } = useTranslation("profile");
  const cache = useQueryClient();
  const [baseline, setBaseline] = useState(profile);
  const [saved, setSaved] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    clearErrors,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<ProfileValues>({ defaultValues: profileValues(profile) });
  const complete = Boolean(
    baseline.first_name && baseline.last_name && baseline.position,
  );
  const message = (key: ProfileField) => {
    const error = errors[key];
    if (!error) return undefined;
    return typeof error.types?.detail === "string"
      ? error.types.detail
      : t(error.message ?? "validation.invalid");
  };
  const submit = handleSubmit(async (values) => {
    setSaved(false);
    clearErrors();
    const parsed = createProfilePatchSchema().safeParse(
      changedProfile(baseline, values),
    );
    if (!parsed.success) {
      parsed.error.issues.forEach((issue, index) => {
        const field = profileFields.find((key) => key === issue.path[0]);
        if (field)
          setError(
            field,
            { message: issue.message },
            { shouldFocus: index === 0 },
          );
      });
      return;
    }
    if (!Object.keys(parsed.data).length) {
      reset(profileValues(baseline));
      return;
    }
    try {
      const updated = await profileApi.patch(parsed.data);
      cache.setQueryData(queryKeys.auth.me, updated);
      setBaseline(updated);
      reset(profileValues(updated));
      setSaved(true);
    } catch (error) {
      if (
        error instanceof ApiError &&
        applyServerValidation(
          error.status,
          { error: { code: error.code, detail: error.detail } },
          profileFields,
          setError,
        )
      )
        return;
      setError("root.server", { message: "saveError" });
    }
  });
  return (
    <div className="profile-grid">
      <aside className="profile-summary">
        <span className="profile-spark" aria-hidden="true">
          ✳
        </span>
        <h2>
          {baseline.first_name
            ? `${baseline.first_name} ${baseline.last_name ?? ""}`.trim()
            : t("newMember")}
        </h2>
        <p className="profile-position">
          {baseline.position || t("noPosition")}
        </p>
        <div className="profile-completeness">
          <h3>{t(complete ? "ready" : "incomplete")}</h3>
          <p>{t(complete ? "readyHint" : "incompleteHint")}</p>
        </div>
        <Link className="profile-settings" to="/settings">
          {t("settings")}
        </Link>
        <ProfilePhoto
          profile={profile}
          refresh={async () => {
            const updated = await profileApi.get();
            cache.setQueryData(queryKeys.auth.me, updated);
          }}
        />
      </aside>
      <section className="profile-form-panel" aria-labelledby="details-title">
        <h2 id="details-title">{t("details")}</h2>
        <p>{t("detailsHint")}</p>
        <form noValidate onSubmit={submit} onChange={() => setSaved(false)}>
          <fieldset>
            <div className="profile-name-fields">
              <Input
                label={t("first_name")}
                autoComplete="given-name"
                readOnly={isSubmitting}
                {...register("first_name")}
                error={message("first_name")}
              />
              <Input
                label={t("last_name")}
                autoComplete="family-name"
                readOnly={isSubmitting}
                {...register("last_name")}
                error={message("last_name")}
              />
            </div>
            <Input
              label={t("position")}
              autoComplete="organization-title"
              readOnly={isSubmitting}
              {...register("position")}
              error={message("position")}
            />
            <Input
              label={t("birth_date")}
              type="date"
              autoComplete="bday"
              readOnly={isSubmitting}
              {...register("birth_date")}
              error={message("birth_date")}
              helperText={t("ageHint")}
            />
            <Textarea
              label={t("bio")}
              rows={4}
              readOnly={isSubmitting}
              {...register("bio")}
              error={message("bio")}
              helperText={t("bioHint")}
            />
            <Input
              label={t("email")}
              type="email"
              value={profile.email}
              readOnly
              helperText={t("emailHint")}
            />
          </fieldset>
          {errors.root?.server && (
            <p role="alert">
              {typeof (errors.root.server as FieldError).types?.detail ===
              "string"
                ? ((errors.root.server as FieldError).types!.detail as string)
                : t(errors.root.server.message ?? "saveError")}
            </p>
          )}
          {saved && (
            <p className="profile-success" role="status">
              {t("saved")}
            </p>
          )}
          <div className="profile-actions">
            <Button
              type="submit"
              variant="lime"
              disabled={!isDirty}
              isLoading={isSubmitting}
            >
              {t(isSubmitting ? "saving" : "save")}
            </Button>
            <Button
              variant="ghost"
              disabled={!isDirty || isSubmitting}
              onClick={() => {
                reset(profileValues(baseline));
                setSaved(false);
              }}
            >
              {t("cancel")}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
export function ProfilePage() {
  const { t } = useTranslation("profile");
  const profile = useQuery({
    queryKey: queryKeys.auth.me,
    queryFn: ({ signal }) => profileApi.get(signal),
    retry: false,
  });
  return (
    <section className="profile-page">
      <header className="profile-heading">
        <p className="eyebrow">{t("eyebrow")}</p>
        <h1>{t("title")}</h1>
        <p>{t("intro")}</p>
      </header>
      {profile.data ? (
        <>
          {profile.isError && (
            <div role="alert">
              <p>{t("refreshError")}</p>
              <Button onClick={() => void profile.refetch()}>
                {t("retry")}
              </Button>
            </div>
          )}
          <ProfileEditor key={profile.data.id} profile={profile.data} />
        </>
      ) : profile.isPending ? (
        <p role="status">{t("load")}</p>
      ) : (
        <div className="profile-form-panel">
          <p role="alert">{t("loadError")}</p>
          <Button onClick={() => void profile.refetch()}>{t("retry")}</Button>
        </div>
      )}
    </section>
  );
}
