import copy from "./copy.en.json";
import { Input } from "../../components/Input";
import { Button } from "../../components/Button";
import { useEffect, useRef, useState, type PropsWithChildren } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { loginSchema, registerSchema } from "./schemas";
import { validationOptions } from "../../lib/validation";
import { applyServerValidation } from "../../lib/server-validation";
import { AuthError } from "./gateway";
import { useAuth } from "./AuthProvider";
import "./auth.css";

const signupSchema = registerSchema
  .extend({ confirm: z.string() })
  .refine((data) => data.password === data.confirm, {
    path: ["confirm"],
    message: copy.passwordsMustMatch,
  });
type Fields = { email: string; password: string; confirm?: string };
function fieldMessage(
  error?: { message?: string; types?: Record<string, unknown> },
  field?: string,
  signup = true,
) {
  if (!error) return "";
  if (error.message === "validation.server")
    return typeof error.types?.detail === "string"
      ? error.types.detail
      : copy.pleaseCheckThisValueAndTryAgain;
  if (field === "email") return copy.enterAValidEmailAddress;
  if (error.message === "validation.tooLong")
    return copy.useNoMoreThan128Characters;
  if (
    !signup &&
    field === "password" &&
    error.message === "validation.tooShort"
  )
    return copy.enterYourPassword;
  if (error.message?.startsWith("validation."))
    return copy.use8128CharactersForYourPassword;
  return error.message;
}
function requestMessage(error: unknown) {
  if (error instanceof AuthError) {
    if (error.status === 401)
      return copy.thatEmailAndPasswordDontMatchPleaseTryAgain;
    if (error.status === 403)
      return copy.verifyYourEmailBeforeSigningInOpenTheLatestVerification;
    if (error.status === 409)
      return copy.thisEmailAlreadyHasAnAccountTrySigningIn;
    if (error.status === 429)
      return copy.tooManyAttemptsPleaseWaitAFewMinutesAndTry;
  }
  return copy.weCouldntReachYourAccountPleaseTryAgain;
}
function AuthFrame({
  title,
  intro,
  children,
}: PropsWithChildren<{ title: string; intro: string }>) {
  useEffect(() => {
    document.title = `${title} · WOZU`;
  }, [title]);
  return (
    <section className="auth-page">
      <aside className="auth-story" aria-label={copy.welcomeToWozu}>
        <span className="eyebrow">{copy.yourNextChapterStartsHere}</span>
        <p className="auth-manifesto">
          {copy.goodWork}
          <br />
          {copy.greatPeople}
          <br />
          <em>{copy.yourKindOfPlace}</em>
        </p>
        <div className="auth-art" aria-hidden="true">
          <span className="auth-orbit" />
          <span className="auth-spark">✳</span>
          <span className="auth-note">
            {copy.aLittle}
            <br />
            <em>{copy.moreHuman}</em>
          </span>
        </div>
        <div className="auth-story-footer">
          <span>{copy.showUpAsYou}</span>
          <span aria-hidden="true">↗</span>
        </div>
      </aside>
      <div className="auth-panel">
        <div className="auth-content">
          <span className="eyebrow">{copy.helloHuman}</span>
          <h1>{title}</h1>
          <p className="auth-intro">{intro}</p>
          {children}
        </div>
      </div>
    </section>
  );
}
export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const signup = mode === "register";
  const auth = useAuth();
  const [params] = useSearchParams();
  const [sent, setSent] = useState(false);
  const [show, setShow] = useState(false);
  const {
    register,
    handleSubmit,
    setError,
    clearErrors,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<Fields>({
    resolver: zodResolver(
      signup ? signupSchema : loginSchema,
      validationOptions,
    ),
    defaultValues: {
      email: "",
      password: "",
      ...(signup ? { confirm: "" } : {}),
    },
  });
  const next = params.get("next");
  const suffix = next ? `?next=${encodeURIComponent(next)}` : "";
  async function submit(data: Fields) {
    clearErrors();
    try {
      if (signup) {
        await auth.register(data);
        reset();
        setSent(true);
      } else await auth.login(data);
    } catch (error) {
      if (
        error instanceof AuthError &&
        applyServerValidation(
          error.status,
          error.payload,
          ["email", "password"],
          setError,
        )
      )
        return;
      setError("root.server", { message: requestMessage(error) });
    }
  }
  if (sent)
    return (
      <AuthFrame
        title={copy.checkYourInbox}
        intro={copy.oneSmallStepThenYoureIn}
      >
        <div className="auth-result" role="status">
          <span className="auth-result-icon" aria-hidden="true">
            ↗
          </span>
          <h2>{copy.yourNextStepIsInYourEmail}</h2>
          <p>
            {copy.ifRegistrationCanProceedYoullReceiveAVerificationLinkCheck}
          </p>
        </div>
        {import.meta.env.DEV && (
          <p className="auth-hint">
            {copy.localDevelopment}{" "}
            <a href="https://localhost/mail" target="_blank" rel="noreferrer">
              {copy.openTheMailpitInbox}
            </a>
            .
          </p>
        )}
        <Link className="button auth-submit" to={`/login${suffix}`}>
          {copy.continueToSignIn}
          <span aria-hidden="true">↗</span>
        </Link>
        <button className="auth-text-button" onClick={() => setSent(false)}>
          {copy.useADifferentEmail}
        </button>
      </AuthFrame>
    );
  return (
    <AuthFrame
      title={signup ? copy.makeYourIntroduction : copy.welcomeBack}
      intro={
        signup
          ? copy.youBringThePersonalityWellHelpYouFindThePossibilities
          : copy.yourPeopleYourPossibilitiesPickUpWhereYouLeftOff
      }
    >
      {!signup && params.get("password") === "updated" && (
        <p role="status">
          {copy.yourPasswordWasUpdatedSignInWithYourNewPassword}
        </p>
      )}
      {!signup && params.get("account") === "deleted" && (
        <p role="status">{copy.yourAccountHasBeenDeactivated}</p>
      )}
      {params.get("logout") === "local" && (
        <p className="auth-alert" role="alert">
          {copy.youreSignedOutHereButWeCouldntRevokeTheServer}
        </p>
      )}
      <form
        noValidate
        onSubmit={handleSubmit(submit)}
        aria-label={signup ? copy.createAccount : copy.signIn}
        aria-busy={isSubmitting}
      >
        {(
          [
            "email",
            "password",
            ...(signup ? (["confirm"] as const) : []),
          ] as const
        ).map((name) => (
          <div className="my-5" key={name}>
            <Input
              id={`auth-${name}`}
              label={
                name === "email"
                  ? copy.emailAddress
                  : name === "confirm"
                    ? copy.confirmPassword
                    : copy.password
              }
              type={name === "email" ? "email" : show ? "text" : "password"}
              autoComplete={
                name === "email"
                  ? "email"
                  : signup
                    ? "new-password"
                    : "current-password"
              }
              autoCapitalize="none"
              spellCheck={false}
              readOnly={isSubmitting}
              required
              className="min-h-12 text-base"
              error={fieldMessage(errors[name], name, signup)}
              helperText={
                signup && name === "password"
                  ? copy["8128CharactersMakeItUniquelyYours"]
                  : undefined
              }
              {...register(name)}
            />
            {name === "password" && (
              <button
                type="button"
                className="mt-2 text-sm underline"
                onClick={() => setShow(!show)}
                aria-label={show ? copy.hidePassword : copy.showPassword}
                aria-pressed={show}
              >
                {show ? copy.hide : copy.show}
              </button>
            )}
          </div>
        ))}
        {errors.root?.server && (
          <p className="auth-alert" role="alert">
            {fieldMessage(errors.root.server)}
          </p>
        )}
        <Button
          className="w-full min-h-12 mt-4"
          type="submit"
          isLoading={isSubmitting}
        >
          {isSubmitting
            ? copy.justAMoment
            : signup
              ? copy.createYourAccount
              : copy.signIn}
          <span aria-hidden="true">↗</span>
        </Button>
      </form>
      <p className="auth-switch">
        {signup ? copy.alreadyFoundUs : copy.newAroundHere}{" "}
        <Link to={`${signup ? "/login" : "/register"}${suffix}`}>
          {signup ? copy.signIn : copy.createAnAccount}
        </Link>
      </p>
      <p className="auth-hint">
        {copy.learnHowWeHandleYourInformationInOur}{" "}
        <Link to="/privacy">{copy.privacyPolicy}</Link> {copy.and}{" "}
        <Link to="/terms">{copy.termsOfService}</Link>.
      </p>
    </AuthFrame>
  );
}
export function VerifyEmail() {
  const auth = useAuth();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [result, setResult] = useState<{
    token: string;
    ok: boolean;
    retry: boolean;
  }>();
  const [attempt, setAttempt] = useState(0);
  const pending = useRef<{
    token: string;
    attempt: number;
    promise: Promise<void>;
  } | null>(null);
  useEffect(() => {
    if (!token) return;
    let active = true;
    if (pending.current?.token !== token || pending.current.attempt !== attempt)
      pending.current = { token, attempt, promise: auth.verify(token) };
    void pending.current.promise.then(
      () => {
        if (active) setResult({ token, ok: true, retry: false });
      },
      (error: unknown) => {
        if (active)
          setResult({
            token,
            ok: false,
            retry: !(
              error instanceof AuthError && [400, 422].includes(error.status)
            ),
          });
      },
    );
    return () => {
      active = false;
    };
  }, [token, attempt, auth]);
  const current = result?.token === token ? result : undefined;
  const checking = Boolean(token && !current);
  const title = checking
    ? copy.aMomentPlease
    : current?.ok
      ? copy.youreVerified
      : copy.letsTryThatAgain;
  return (
    <AuthFrame title={title} intro={copy.aSecureStartToYourNextChapter}>
      <div
        className="auth-result"
        role={checking || current?.ok ? "status" : "alert"}
      >
        <span className="auth-result-icon" aria-hidden="true">
          {current?.ok ? "✓" : "↗"}
        </span>
        <p>
          {checking
            ? copy.checkingYourVerificationLink
            : current?.ok
              ? copy.yourEmailIsConfirmedYouCanNowSignIn
              : !token
                ? copy.thisLinkIsMissingItsVerificationTokenOpenTheFull
                : current?.retry
                  ? copy.weCouldntVerifyYourEmailRightNowCheckYourConnection
                  : copy.thisLinkIsInvalidExpiredOrHasBeenReplacedUse}
        </p>
      </div>
      {current?.retry && (
        <button
          className="button auth-submit"
          onClick={() => {
            setResult(undefined);
            setAttempt((n) => n + 1);
          }}
        >
          {copy.tryVerificationAgain}
        </button>
      )}
      {!checking && (
        <Link
          className="button auth-submit"
          to={current?.ok ? "/login" : "/register"}
        >
          {current?.ok ? copy.continueToSignIn : copy.backToRegistration}
          <span aria-hidden="true">↗</span>
        </Link>
      )}
    </AuthFrame>
  );
}
export function LogoutButton() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  async function logout() {
    setPending(true);
    try {
      await auth.logout();
      void navigate("/login", { replace: true });
    } catch {
      void navigate("/login?logout=local", { replace: true });
    } finally {
      setPending(false);
    }
  }
  return (
    <button
      className="auth-logout"
      disabled={pending}
      onClick={() => void logout()}
    >
      {pending ? copy.signingOut : copy.signOut}
    </button>
  );
}
