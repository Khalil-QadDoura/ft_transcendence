import "../../i18n";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, type FieldError } from "react-hook-form";
import { ApiError, queryKeys } from "../../api/client";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Input } from "../../components/Input";
import { Modal, ModalFooter } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { Textarea } from "../../components/Textarea";
import { applyServerValidation } from "../../lib/server-validation";
import {
  companyApi,
  companyLogoApi,
  type Company,
  type CompanyCreatePayload,
  type CompanyUpdatePayload,
} from "./api";
import { companyCreateSchema, companyUpdateSchema } from "./schemas";
import "./company.css";

const createFields = [
  "name",
  "description",
  "country",
  "city",
  "district",
] as const;
type CreateField = (typeof createFields)[number];
type CreateValues = Record<CreateField, string>;

const editFields = [
  "name",
  "country",
  "city",
  "district",
  "country_code",
] as const;
type EditField = (typeof editFields)[number];
type EditValues = Record<EditField, string>;

function editValuesFrom(company: Company): EditValues {
  return {
    name: company.name ?? "",
    country: company.country ?? "",
    city: company.city ?? "",
    district: company.district ?? "",
    country_code: company.country_code ?? "",
  };
}

function emptyCreateValues(): CreateValues {
  return {
    name: "",
    description: "",
    country: "",
    city: "",
    district: "",
  };
}

function CompanyLogoSection({
  company,
  refresh,
}: {
  company: Company;
  refresh: () => Promise<unknown>;
}) {
  const { t } = useTranslation("company");
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
      await companyLogoApi.upload(file, pending.signal, setProgress);
      await refresh();
      if (!pending.signal.aborted) {
        reset();
        setSaved(true);
      }
    } catch (err) {
      if (!pending.signal.aborted) {
        if (err instanceof ApiError && err.status === 415) {
          reset();
          setError(t("logoInvalid"));
        } else if (err instanceof ApiError && err.status === 413) {
          reset();
          setError(t("logoTooBig"));
        } else {
          setError(t("logoError"));
        }
      }
    } finally {
      if (!pending.signal.aborted) setBusy(false);
    }
  }

  return (
    <section
      className="company-logo-panel"
      aria-labelledby="company-logo-title"
    >
      <h3 id="company-logo-title">{t("logo")}</h3>
      <Avatar
        key={company.logo_url ?? "none"}
        src={company.logo_url ?? undefined}
        alt={company.name}
        fallbackText={company.name}
        size="xl"
      />
      {file && preview && (
        <img
          className="company-logo-preview"
          src={preview}
          alt={t("logoPreview")}
        />
      )}
      <p>{t("logoHint")}</p>
      <input
        ref={input}
        className="sr-only"
        tabIndex={-1}
        type="file"
        id="company-logo-input"
        aria-label={t("chooseLogo")}
        accept="image/jpeg,image/png,image/webp"
        disabled={busy}
        onChange={(event) => {
          const next = event.target.files?.[0];
          setSaved(false);
          setError("");
          reset();
          if (!next) return;
          const invalid = companyLogoApi.fileError(next);
          if (invalid) {
            setError(t(invalid === "type" ? "logoType" : "logoSize"));
          } else {
            setFile(next);
          }
        }}
      />
      <Button
        type="button"
        variant="outline"
        disabled={busy}
        onClick={() => input.current?.click()}
      >
        {t("chooseLogo")}
      </Button>
      {file && (
        <div className="company-logo-actions">
          <Button type="button" isLoading={busy} onClick={() => void upload()}>
            {t(busy ? "uploadingLogo" : "uploadLogo")}
          </Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={reset}>
            {t("removePreview")}
          </Button>
        </div>
      )}
      {busy && (
        <progress aria-label={t("logoProgress")} max="100" value={progress} />
      )}
      {error && <p role="alert">{error}</p>}
      {saved && <p role="status">{t("logoSaved")}</p>}
    </section>
  );
}

function CreateCompanyForm({
  onCreated,
  onCancel,
}: {
  onCreated: (company: Company) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation("company");
  const {
    register,
    handleSubmit,
    setError,
    clearErrors,
    formState: { errors, isSubmitting },
  } = useForm<CreateValues>({ defaultValues: emptyCreateValues() });

  const message = (key: CreateField) => {
    const error = errors[key];
    if (!error) return undefined;
    return typeof error.types?.detail === "string"
      ? error.types.detail
      : t(error.message ?? "validation.invalid");
  };

  const submit = handleSubmit(async (values) => {
    clearErrors();
    const candidate: CompanyCreatePayload = {
      name: values.name,
      description: values.description.trim() || null,
      country: values.country.trim() || null,
      city: values.city.trim() || null,
      district: values.district.trim() || null,
    };
    const parsed = companyCreateSchema.safeParse(candidate);
    if (!parsed.success) {
      parsed.error.issues.forEach((issue, index) => {
        const field = createFields.find((key) => key === issue.path[0]);
        if (field) {
          setError(
            field,
            { message: issue.message },
            { shouldFocus: index === 0 },
          );
        }
      });
      return;
    }

    try {
      const created = await companyApi.create(parsed.data);
      onCreated(created);
    } catch (error) {
      if (
        error instanceof ApiError &&
        applyServerValidation(
          error.status,
          { error: { code: error.code, detail: error.detail } },
          createFields,
          setError,
        )
      ) {
        return;
      }
      setError("root.server", { message: "createError" });
    }
  });

  return (
    <section
      className="company-form-panel"
      aria-labelledby="create-company-title"
    >
      <h2 id="create-company-title">{t("createHeading")}</h2>
      <p>{t("createHint")}</p>
      <form noValidate onSubmit={submit}>
        <fieldset>
          <Input
            label={t("name")}
            placeholder={t("namePlaceholder")}
            readOnly={isSubmitting}
            {...register("name")}
            error={message("name")}
          />
          <Textarea
            label={t("description")}
            placeholder={t("descriptionPlaceholder")}
            helperText={t("descriptionHint")}
            rows={4}
            readOnly={isSubmitting}
            {...register("description")}
            error={message("description")}
          />
          <div className="company-two-col">
            <Input
              label={t("country")}
              placeholder={t("countryPlaceholder")}
              readOnly={isSubmitting}
              {...register("country")}
              error={message("country")}
            />
            <Input
              label={t("city")}
              placeholder={t("cityPlaceholder")}
              readOnly={isSubmitting}
              {...register("city")}
              error={message("city")}
            />
          </div>
          <Input
            label={t("district")}
            placeholder={t("districtPlaceholder")}
            readOnly={isSubmitting}
            {...register("district")}
            error={message("district")}
          />
        </fieldset>
        {errors.root?.server && (
          <p role="alert">
            {typeof (errors.root.server as FieldError).types?.detail ===
            "string"
              ? ((errors.root.server as FieldError).types!.detail as string)
              : t(errors.root.server.message ?? "createError")}
          </p>
        )}
        <div className="company-actions">
          <Button type="submit" variant="lime" isLoading={isSubmitting}>
            {t(isSubmitting ? "creating" : "createSubmit")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={isSubmitting}
            onClick={onCancel}
          >
            {t("cancel")}
          </Button>
        </div>
      </form>
    </section>
  );
}

function CompanyEditor({
  company,
  justCreated,
  onDeleted,
}: {
  company: Company;
  justCreated: boolean;
  onDeleted: () => void;
}) {
  const { t } = useTranslation("company");
  const cache = useQueryClient();
  const [baseline, setBaseline] = useState(company);
  const [saved, setSaved] = useState(justCreated);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    setBaseline(company);
  }, [company]);

  const {
    register,
    handleSubmit,
    reset,
    setError,
    clearErrors,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<EditValues>({ defaultValues: editValuesFrom(company) });

  const message = (key: EditField) => {
    const error = errors[key];
    if (!error) return undefined;
    return typeof error.types?.detail === "string"
      ? error.types.detail
      : t(error.message ?? "validation.invalid");
  };

  const submit = handleSubmit(async (values) => {
    setSaved(false);
    clearErrors();
    const candidate: CompanyUpdatePayload = {
      name: values.name,
      country: values.country,
      city: values.city,
      district: values.district.trim() || null,
      country_code: values.country_code.trim() || null,
    };
    const parsed = companyUpdateSchema.safeParse(candidate);
    if (!parsed.success) {
      parsed.error.issues.forEach((issue, index) => {
        const field = editFields.find((key) => key === issue.path[0]);
        if (field) {
          setError(
            field,
            { message: issue.message },
            { shouldFocus: index === 0 },
          );
        }
      });
      return;
    }

    try {
      const updated = await companyApi.patch(parsed.data);
      cache.setQueryData(queryKeys.companies.me, updated);
      setBaseline(updated);
      reset(editValuesFrom(updated));
      setSaved(true);
    } catch (error) {
      if (
        error instanceof ApiError &&
        applyServerValidation(
          error.status,
          { error: { code: error.code, detail: error.detail } },
          editFields,
          setError,
        )
      ) {
        return;
      }
      setError("root.server", { message: "saveError" });
    }
  });

  async function handleDelete() {
    if (deleting) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await companyApi.remove();
      cache.setQueryData(queryKeys.companies.me, null);
      setConfirmOpen(false);
      onDeleted();
    } catch {
      setDeleteError(t("deleteError"));
    } finally {
      setDeleting(false);
    }
  }

  const locationLine = [baseline.district, baseline.city, baseline.country]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="company-grid">
      <aside className="company-summary">
        <span className="company-spark" aria-hidden="true">
          ✳
        </span>
        <h2>{baseline.name}</h2>
        <p className="company-location">{locationLine || t("noLocation")}</p>
        {baseline.description && (
          <p className="company-description-copy">{baseline.description}</p>
        )}
        <Link className="company-jobs-link" to="/employer/jobs">
          {t("manageJobs")}
        </Link>
        <CompanyLogoSection
          company={baseline}
          refresh={async () => {
            const refreshed = await companyApi.get();
            cache.setQueryData(queryKeys.companies.me, refreshed);
            if (refreshed) setBaseline(refreshed);
          }}
        />
      </aside>

      <section
        className="company-form-panel"
        aria-labelledby="company-details-title"
      >
        <h2 id="company-details-title">{t("details")}</h2>
        <p>{t("detailsHint")}</p>
        <form noValidate onSubmit={submit} onChange={() => setSaved(false)}>
          <fieldset>
            <Input
              label={t("name")}
              placeholder={t("namePlaceholder")}
              readOnly={isSubmitting}
              {...register("name")}
              error={message("name")}
            />
            <div className="company-two-col">
              <Input
                label={t("country")}
                placeholder={t("countryPlaceholder")}
                readOnly={isSubmitting}
                {...register("country")}
                error={message("country")}
              />
              <Input
                label={t("city")}
                placeholder={t("cityPlaceholder")}
                readOnly={isSubmitting}
                {...register("city")}
                error={message("city")}
              />
            </div>
            <div className="company-two-col">
              <Input
                label={t("district")}
                placeholder={t("districtPlaceholder")}
                readOnly={isSubmitting}
                {...register("district")}
                error={message("district")}
              />
              <Input
                label={t("countryCode")}
                placeholder={t("countryCodePlaceholder")}
                helperText={t("countryCodeHint")}
                readOnly={isSubmitting}
                {...register("country_code")}
                error={message("country_code")}
              />
            </div>
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
            <p className="company-success" role="status">
              {t(justCreated ? "created" : "saved")}
            </p>
          )}
          <div className="company-actions">
            <Button
              type="submit"
              variant="lime"
              disabled={!isDirty}
              isLoading={isSubmitting}
            >
              {t(isSubmitting ? "saving" : "save")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={!isDirty || isSubmitting}
              onClick={() => {
                reset(editValuesFrom(baseline));
                setSaved(false);
              }}
            >
              {t("cancel")}
            </Button>
          </div>
        </form>

        <div className="company-danger">
          <h3>{t("dangerTitle")}</h3>
          <p>{t("dangerHint")}</p>
          <Button
            type="button"
            variant="danger"
            onClick={() => {
              setDeleteError("");
              setConfirmOpen(true);
            }}
          >
            {t("deleteButton")}
          </Button>
        </div>

        <Modal
          isOpen={confirmOpen}
          onClose={() => {
            if (!deleting) setConfirmOpen(false);
          }}
          title={t("deleteModalTitle")}
          description={t("deleteModalDescription")}
          size="sm"
        >
          {deleteError && <p role="alert">{deleteError}</p>}
          <ModalFooter>
            <Button
              type="button"
              variant="ghost"
              disabled={deleting}
              onClick={() => setConfirmOpen(false)}
            >
              {t("cancel")}
            </Button>
            <Button
              type="button"
              variant="danger"
              isLoading={deleting}
              onClick={() => void handleDelete()}
            >
              {t(deleting ? "deleting" : "confirmDelete")}
            </Button>
          </ModalFooter>
        </Modal>
      </section>
    </div>
  );
}

export function CompanyPage() {
  const { t } = useTranslation("company");
  const cache = useQueryClient();
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [justCreated, setJustCreated] = useState(false);
  const [justDeleted, setJustDeleted] = useState(false);

  const query = useQuery({
    queryKey: queryKeys.companies.me,
    queryFn: ({ signal }) => companyApi.get(signal),
    retry: false,
  });

  return (
    <section className="company-page">
      <header className="company-heading">
        <p className="eyebrow">{t("eyebrow")}</p>
        <h1>{t("title")}</h1>
        <p>{t("intro")}</p>
      </header>

      {query.isPending ? (
        <div role="status" className="flex items-center gap-3">
          <Spinner size="md" />
          <span>{t("load")}</span>
        </div>
      ) : query.isError ? (
        <div className="company-form-panel">
          <p role="alert">{t("loadError")}</p>
          <Button type="button" onClick={() => void query.refetch()}>
            {t("retry")}
          </Button>
        </div>
      ) : query.data ? (
        <CompanyEditor
          key={query.data.id}
          company={query.data}
          justCreated={justCreated}
          onDeleted={() => {
            setJustCreated(false);
            setShowCreateForm(false);
            setJustDeleted(true);
          }}
        />
      ) : showCreateForm ? (
        <CreateCompanyForm
          onCreated={(created) => {
            cache.setQueryData(queryKeys.companies.me, created);
            setShowCreateForm(false);
            setJustDeleted(false);
            setJustCreated(true);
          }}
          onCancel={() => setShowCreateForm(false)}
        />
      ) : (
        <div className="company-form-panel">
          {justDeleted && (
            <p className="company-success" role="status">
              {t("deleted")}
            </p>
          )}
          <EmptyState
            title={t("emptyTitle")}
            description={t("emptyDescription")}
            action={
              <Button
                type="button"
                variant="lime"
                onClick={() => {
                  setJustDeleted(false);
                  setShowCreateForm(true);
                }}
              >
                {t("createCta")}
              </Button>
            }
          />
        </div>
      )}
    </section>
  );
}
