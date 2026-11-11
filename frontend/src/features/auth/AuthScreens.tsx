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
    message: "Passwords must match.",
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
      : "Please check this value and try again.";
  if (field === "email") return "Enter a valid email address.";
  if (error.message === "validation.tooLong")
    return "Use no more than 128 characters.";
  if (
    !signup &&
    field === "password" &&
    error.message === "validation.tooShort"
  )
    return "Enter your password.";
  if (error.message?.startsWith("validation."))
    return "Use 8–128 characters for your password.";
  return error.message;
}
function requestMessage(error: unknown) {
  if (error instanceof AuthError) {
    if (error.status === 401)
      return "That email and password don’t match. Please try again.";
    if (error.status === 403)
      return "Verify your email before signing in. Open the latest verification link in your inbox.";
    if (error.status === 409)
      return "This email already has an account. Try signing in.";
    if (error.status === 429)
      return "Too many attempts. Please wait a few minutes and try again.";
  }
  return "We couldn’t reach your account. Please try again.";
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
      <aside className="auth-story" aria-label="Welcome to WOZU">
        <span className="eyebrow">YOUR NEXT CHAPTER STARTS HERE</span>
        <p className="auth-manifesto">
          Good work.
          <br />
          Great people.
          <br />
          <em>Your kind of place.</em>
        </p>
        <div className="auth-art" aria-hidden="true">
          <span className="auth-orbit" />
          <span className="auth-spark">✳</span>
          <span className="auth-note">
            A little
            <br />
            <em>more human.</em>
          </span>
        </div>
        <div className="auth-story-footer">
          <span>SHOW UP AS YOU.</span>
          <span aria-hidden="true">↗</span>
        </div>
      </aside>
      <div className="auth-panel">
        <div className="auth-content">
          <span className="eyebrow">HELLO, HUMAN.</span>
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
        title="Check your inbox."
        intro="One small step, then you’re in."
      >
        <div className="auth-result" role="status">
          <span className="auth-result-icon" aria-hidden="true">
            ↗
          </span>
          <h2>Your next step is in your email.</h2>
          <p>
            If registration can proceed, you’ll receive a verification link.
            Check spam, and always use the newest link.
          </p>
        </div>
        {import.meta.env.DEV && (
          <p className="auth-hint">
            Local development:{" "}
            <a href="https://localhost/mail" target="_blank" rel="noreferrer">
              open the Mailpit inbox ↗
            </a>
            .
          </p>
        )}
        <Link className="button auth-submit" to={`/login${suffix}`}>
          Continue to sign in <span aria-hidden="true">↗</span>
        </Link>
        <button className="auth-text-button" onClick={() => setSent(false)}>
          Use a different email
        </button>
      </AuthFrame>
    );
  return (
    <AuthFrame
      title={signup ? "Make your introduction." : "Welcome back."}
      intro={
        signup
          ? "You bring the personality. We’ll help you find the possibilities."
          : "Your people. Your possibilities. Pick up where you left off."
      }
    >
      {params.get("logout") === "local" && (
        <p className="auth-alert" role="alert">
          You’re signed out here, but we couldn’t revoke the server session.
          Close this tab on a shared device and try again when connected.
        </p>
      )}
      <form
        noValidate
        onSubmit={handleSubmit(submit)}
        aria-label={signup ? "Create account" : "Sign in"}
        aria-busy={isSubmitting}
      >
        {(
          [
            "email",
            "password",
            ...(signup ? (["confirm"] as const) : []),
          ] as const
        ).map((name) => (
          <div className="auth-field" key={name}>
            <label htmlFor={`auth-${name}`}>
              {name === "email"
                ? "Email address"
                : name === "confirm"
                  ? "Confirm password"
                  : "Password"}
            </label>
            <div className="auth-input-wrap">
              <input
                id={`auth-${name}`}
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
                aria-invalid={Boolean(errors[name])}
                aria-describedby={
                  errors[name]
                    ? `${name}-error`
                    : signup && name === "password"
                      ? "password-hint"
                      : undefined
                }
                {...register(name)}
              />
              {name === "password" && (
                <button
                  type="button"
                  className="auth-reveal"
                  onClick={() => setShow(!show)}
                  aria-label={show ? "Hide password" : "Show password"}
                  aria-pressed={show}
                >
                  {show ? "Hide" : "Show"}
                </button>
              )}
            </div>
            {signup && name === "password" && (
              <small id="password-hint">
                8–128 characters. Make it uniquely yours.
              </small>
            )}
            {errors[name] && (
              <p className="auth-field-error" id={`${name}-error`} role="alert">
                {fieldMessage(errors[name], name, signup)}
              </p>
            )}
          </div>
        ))}
        {errors.root?.server && (
          <p className="auth-alert" role="alert">
            {fieldMessage(errors.root.server)}
          </p>
        )}
        <button
          className="button auth-submit"
          type="submit"
          disabled={isSubmitting}
        >
          {isSubmitting
            ? "Just a moment…"
            : signup
              ? "Create your account"
              : "Sign in"}
          <span aria-hidden="true">↗</span>
        </button>
      </form>
      <p className="auth-switch">
        {signup ? "Already found us?" : "New around here?"}{" "}
        <Link to={`${signup ? "/login" : "/register"}${suffix}`}>
          {signup ? "Sign in" : "Create an account"}
        </Link>
      </p>
      <p className="auth-hint">
        Learn how we handle your information in our{" "}
        <Link to="/privacy">Privacy Policy</Link> and{" "}
        <Link to="/terms">Terms of Service</Link>.
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
    ? "A moment, please."
    : current?.ok
      ? "You’re verified."
      : "Let’s try that again.";
  return (
    <AuthFrame title={title} intro="A secure start to your next chapter.">
      <div
        className="auth-result"
        role={checking || current?.ok ? "status" : "alert"}
      >
        <span className="auth-result-icon" aria-hidden="true">
          {current?.ok ? "✓" : "↗"}
        </span>
        <p>
          {checking
            ? "Checking your verification link…"
            : current?.ok
              ? "Your email is confirmed. You can now sign in."
              : !token
                ? "This link is missing its verification token. Open the full link from your email."
                : current?.retry
                  ? "We couldn’t verify your email right now. Check your connection and try again."
                  : "This link is invalid, expired or has been replaced. Use the latest email, or register again to request a new link."}
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
          Try verification again
        </button>
      )}
      {!checking && (
        <Link
          className="button auth-submit"
          to={current?.ok ? "/login" : "/register"}
        >
          {current?.ok ? "Continue to sign in" : "Back to registration"}
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
      {pending ? "Signing out…" : "Sign out"}
    </button>
  );
}
