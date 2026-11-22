import sourceCopy from "../../i18n/en/account.json";
import { translatedCopy, localizeMessage } from "../../i18n/copy";
const copy = translatedCopy("account", sourceCopy);
import { LanguageSwitcher } from "../../i18n/LanguageSwitcher";
import { useTranslation } from "react-i18next";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Input } from "../../components/Input";
import { Button } from "../../components/Button";
import { Modal } from "../../components/Modal";
import { ApiError } from "../../api/client";
import { registerSchema } from "../auth/schemas";
import { validationOptions } from "../../lib/validation";
import { accountApi } from "./api";
import "./account.css";
const forgotSchema = registerSchema.pick({ email: true });
const passwordSchema = z
  .object({
    new_password: registerSchema.shape.password,
    confirm: z.string(),
    current_password: z.string().max(128),
  })
  .refine((v) => v.new_password === v.confirm, {
    path: ["confirm"],
    message: "validation.passwordsMatch",
  });
type PasswordFields = z.infer<typeof passwordSchema>;
function errorText(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 400)
      return typeof error.detail === "string"
        ? error.detail
        : copy.pleaseCheckYourDetailsAndTryAgain;
    if (error.status === 429)
      return copy.tooManyAttemptsPleaseWaitAFewMinutesAndTry;
    if (error.status === 422) return copy.pleaseCheckTheFormValuesAndTryAgain;
  }
  return copy.weCouldntCompleteThatRequestPleaseTryAgain;
}
export function ForgotPassword() {
  useTranslation("account");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof forgotSchema>>({
    resolver: zodResolver(forgotSchema, validationOptions),
  });
  return (
    <section className="account-page">
      <div className="account-heading">
        <p className="eyebrow">{copy.aWayBackIn}</p>
        <h1>{copy.forgotYourPassword}</h1>
        <p>{copy.wellHelpYouGetBackToYourNextChapter}</p>
      </div>
      <div className="account-panel">
        {sent ? (
          <div role="status">
            <h2>{copy.checkYourInbox}</h2>
            <p>{copy.ifThisEmailHasAnEligibleAccountAResetLink}</p>
          </div>
        ) : (
          <form
            noValidate
            onSubmit={handleSubmit(async ({ email }) => {
              setError("");
              try {
                await accountApi.forgot(email);
                setSent(true);
              } catch (e) {
                setError(errorText(e));
              }
            })}
          >
            <Input
              label={copy.emailAddress}
              type="email"
              autoComplete="email"
              required
              {...register("email")}
              error={errors.email && copy.enterAValidEmailAddress}
            />
            {error && <p role="alert">{localizeMessage("account", error)}</p>}
            <Button type="submit" isLoading={isSubmitting}>
              {copy.sendResetLink}
            </Button>
          </form>
        )}
        <Link to="/login">{copy.backToSignIn}</Link>
      </div>
    </section>
  );
}
function PasswordForm({ token }: { token?: string }) {
  useTranslation("account");
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const changing = token === undefined;
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<PasswordFields>({
    resolver: zodResolver(passwordSchema, validationOptions),
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });
  return (
    <form
      noValidate
      onSubmit={handleSubmit(async (values) => {
        setError("");
        try {
          if (changing)
            await accountApi.change(
              values.current_password,
              values.new_password,
            );
          else await accountApi.reset(token, values.new_password);
          navigate("/login?password=updated", { replace: true });
        } catch (e) {
          setError(errorText(e));
        }
      })}
    >
      {changing && (
        <Input
          label={copy.currentPassword}
          type="password"
          autoComplete="current-password"
          required
          {...register("current_password")}
          error={errors.current_password && copy.useNoMoreThan128Characters}
        />
      )}
      <Input
        label={copy.newPassword}
        type="password"
        autoComplete="new-password"
        required
        {...register("new_password")}
        helperText={copy.use8128Characters}
        error={errors.new_password && copy.use8128Characters}
      />
      <Input
        label={copy.confirmNewPassword}
        type="password"
        autoComplete="new-password"
        required
        {...register("confirm")}
        error={errors.confirm && copy.passwordsMustMatch}
      />
      {error && <p role="alert">{localizeMessage("account", error)}</p>}
      <Button type="submit" isLoading={isSubmitting}>
        {changing ? copy.changePassword : copy.resetPassword}
      </Button>
    </form>
  );
}
export function ResetPassword() {
  useTranslation("account");
  const [params] = useSearchParams();
  const token = params.get("token");
  return (
    <section className="account-page">
      <div className="account-heading">
        <p className="eyebrow">{copy.aFreshStart}</p>
        <h1>{copy.chooseANewPassword}</h1>
        <p>{copy.yourResetLinkWorksOnceAfterResettingSignInAgain}</p>
      </div>
      <div className="account-panel">
        {token ? (
          <PasswordForm key={token} token={token} />
        ) : (
          <p role="alert">{copy.thisResetLinkIsMissingItsTokenRequestANew}</p>
        )}
        <Link to="/forgot-password">{copy.requestANewResetLink}</Link>
      </div>
    </section>
  );
}
export function AccountSettings() {
  useTranslation("account");
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const close = () => {
    if (!removing) setConfirm(false);
  };
  return (
    <section className="account-page">
      <div className="account-heading">
        <p className="eyebrow">{copy.yourAccountYourChoice}</p>
        <h1>{copy.accountSettings}</h1>
        <p>{copy.keepYourAccountSecureAndStayInControl}</p>
        <Link to="/profile">{copy.backToMyProfile}</Link>
      </div>
      <div className="account-panel">
        <section
          className="account-language"
          aria-labelledby="settings-language"
        >
          <div>
            <h2 id="settings-language">{t("language")}</h2>
            <p>{copy.chooseTheLanguageUsedOnThisDevice}</p>
          </div>
          <LanguageSwitcher />
        </section>
        <h2>{copy.changePassword}</h2>
        <p>{copy.thisSignsYouOutOnAllDevicesYoullSignIn}</p>
        <PasswordForm />
        <div className="account-danger">
          <h2>{copy.deleteAccount}</h2>
          <p>{copy.yourAccountWillBeDeactivatedImmediatelyAndYouWontBe}</p>
          <Link to="/privacy">{copy.privacyPolicy}</Link>
          <Button
            variant="danger"
            onClick={() => {
              setError("");
              setConfirm(true);
            }}
          >
            {copy.deleteAccount}
          </Button>
        </div>
        <Modal
          isOpen={confirm}
          onClose={close}
          title={copy.deleteYourAccount}
          description={
            copy.thisDeactivatesYourAccountAndEndsYourSessionsYouWont
          }
          closeOnBackdrop={!removing}
        >
          {error && <p role="alert">{localizeMessage("account", error)}</p>}
          <div className="account-actions">
            <Button variant="outline" disabled={removing} onClick={close}>
              {copy.keepMyAccount}
            </Button>
            <Button
              variant="danger"
              isLoading={removing}
              onClick={async () => {
                setRemoving(true);
                setError("");
                try {
                  await accountApi.remove();
                  navigate("/login?account=deleted", { replace: true });
                } catch (e) {
                  setError(errorText(e));
                } finally {
                  setRemoving(false);
                }
              }}
            >
              {copy.yesDeleteMyAccount}
            </Button>
          </div>
        </Modal>
      </div>
    </section>
  );
}
