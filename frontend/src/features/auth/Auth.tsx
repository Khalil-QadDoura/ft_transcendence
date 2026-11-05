import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useForm, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { ArrowRight, Eye, EyeOff, ShieldCheck, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, post, safeNext, setTokens, type Tokens } from "../../api/client";
import {
  Button,
  ErrorNotice,
  Field,
  Loading,
  Success,
  useAction,
} from "../../components/ui";
import { credentials, emailSchema } from "./schemas";
import { Wordmark } from "../../app/Layout";
import { HeroArtwork } from "../jobs/Jobs";

export function AuthPage({
  mode,
}: {
  mode: "login" | "register" | "forgot" | "reset" | "verify";
}) {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [show, setShow] = useState(false);
  const schema =
    mode === "forgot"
      ? emailSchema
      : mode === "reset"
        ? z.object({ password: credentials.shape.password })
        : credentials;
  const form = useForm<{ email?: string; password?: string }>({
    resolver: zodResolver(schema) as Resolver<{
      email?: string;
      password?: string;
    }>,
    defaultValues: { email: "", password: "" },
  });
  const action = useAction(
    async (data: { email?: string; password?: string }) => {
      if (mode === "login") {
        const tokens = await post<Tokens>("/auth/login", data);
        setTokens(tokens);
        navigate(safeNext(params.get("next")), { replace: true });
      }
      if (mode === "register") await post("/auth/register", data);
      if (mode === "forgot")
        await post("/auth/forgot-password", { email: data.email });
      if (mode === "reset")
        await post("/auth/reset-password", {
          token: params.get("token"),
          new_password: data.password,
        });
    },
  );
  const verify = useQuery({
    queryKey: ["verify-email", params.get("token")],
    queryFn: () =>
      api<{ verified: boolean; email: string }>(
        `/auth/verify?token=${encodeURIComponent(params.get("token") || "")}`,
      ),
    enabled: mode === "verify" && !!params.get("token"),
    retry: false,
    staleTime: Infinity,
  });
  const titles = {
    login: "Welcome back, you.",
    register: "Your story starts here.",
    forgot: "Let’s get you back in.",
    reset: "A fresh start.",
    verify: "One small step. A new beginning.",
  };
  const subtitles = {
    login: "Good things happen when you show up.",
    register: "Find your people. Find your purpose. Find your next.",
    forgot: "We’ll send you a link to reset your password.",
    reset: "Choose a strong password for your next chapter.",
    verify: "Verify your email to make it official.",
  };
  return (
    <div className="auth-layout">
      <section className="auth-story">
        <Wordmark />
        <div className="auth-story-copy">
          <span className="eyebrow">
            <Sparkles size={16} /> {t("A LITTLE MORE HUMAN")}
          </span>
          <h1>
            {t("You are more")}
            <br />
            {t("than a résumé")}
            <span>.</span>
          </h1>
          <p>
            {t(
              "Find work that sees your potential. Meet people who get you. Start something that matters.",
            )}
          </p>
          <HeroArtwork />
        </div>
        <p className="auth-story-foot">
          {t("Your skills. Your story. Your next chapter.")}
        </p>
      </section>
      <section className="auth-form-side">
        <div className="auth-top-link">
          <Link to="/jobs">← {t("Explore opportunities")}</Link>
        </div>
        <div className="auth-form-card">
          <span className="eyebrow">
            WOZU / {t(mode === "login" ? "WELCOME BACK" : "YOUR NEXT CHAPTER")}
          </span>
          <h2>{t(titles[mode])}</h2>
          <p className="auth-subtitle">{t(subtitles[mode])}</p>
          {mode === "verify" ? (
            <>
              {!params.get("token") ? (
                <ErrorNotice
                  error={
                    new Error(t("Open the verification link from your email."))
                  }
                />
              ) : verify.isPending ? (
                <Loading />
              ) : verify.error ? (
                <ErrorNotice error={verify.error} />
              ) : (
                <Success>
                  {t("Email verified. You’re ready to sign in.")}
                </Success>
              )}
              <Link className="button primary full" to="/login">
                {t("Sign in")}
                <ArrowRight size={18} />
              </Link>
            </>
          ) : action.isSuccess && mode !== "login" ? (
            <>
              <Success>
                {t(
                  mode === "register"
                    ? "Check your inbox for your verification link."
                    : mode === "forgot"
                      ? "If this email is registered, a reset link is on its way."
                      : "Password updated. Sign in with your new password.",
                )}
              </Success>
              <Link className="button secondary full" to="/login">
                {t("Back to sign in")}
              </Link>
            </>
          ) : (
            <form
              onSubmit={form.handleSubmit((data) => action.mutate(data))}
              noValidate
            >
              <ErrorNotice error={action.error} />
              {mode !== "reset" && (
                <Field
                  label="Email address"
                  error={form.formState.errors.email?.message}
                >
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    {...form.register("email")}
                    aria-invalid={!!form.formState.errors.email}
                  />
                </Field>
              )}
              {mode !== "forgot" && (
                <Field
                  label={mode === "reset" ? "New password" : "Password"}
                  error={form.formState.errors.password?.message}
                  hint={
                    mode === "register"
                      ? "At least 8 characters. Make it something only you know."
                      : undefined
                  }
                >
                  <span className="password-input">
                    <input
                      type={show ? "text" : "password"}
                      autoComplete={
                        mode === "login" ? "current-password" : "new-password"
                      }
                      {...form.register("password")}
                      aria-invalid={!!form.formState.errors.password}
                    />
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={t(show ? "Hide password" : "Show password")}
                      onClick={() => setShow(!show)}
                    >
                      {show ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </span>
                </Field>
              )}
              {mode === "login" && (
                <div className="form-link-row">
                  <Link to="/forgot-password">{t("Forgot password?")}</Link>
                </div>
              )}
              {mode === "register" && (
                <p className="small-text muted">
                  {t("By creating an account, you agree to our")}{" "}
                  <Link to="/terms">{t("Terms")}</Link> {t("and")}{" "}
                  <Link to="/privacy">{t("Privacy policy")}</Link>.
                </p>
              )}
              <Button
                className="full"
                type="submit"
                busy={action.isPending}
                disabled={mode === "reset" && !params.get("token")}
              >
                {t(
                  mode === "login"
                    ? "Let’s get started"
                    : mode === "register"
                      ? "Create my account"
                      : mode === "forgot"
                        ? "Send reset link"
                        : "Update password",
                )}
                <ArrowRight size={18} />
              </Button>
              {mode === "reset" && !params.get("token") && (
                <ErrorNotice
                  error={new Error(t("Open the reset link from your email."))}
                />
              )}
            </form>
          )}
          {mode === "login" ? (
            <p className="auth-switch">
              {t("New around here?")}{" "}
              <Link to="/register">{t("Make yourself at home")}</Link>
            </p>
          ) : mode === "register" ? (
            <p className="auth-switch">
              {t("Already part of WOZU?")}{" "}
              <Link to="/login">{t("Sign in")}</Link>
            </p>
          ) : null}
          <div className="auth-trust">
            <ShieldCheck size={16} />
            {t("Your story is safe with us.")}
          </div>
        </div>
        <div className="auth-bottom">
          © {new Date().getFullYear()} WOZU{" "}
          <Link to="/privacy">{t("Privacy")}</Link>
          <Link to="/terms">{t("Terms")}</Link>
        </div>
      </section>
    </div>
  );
}
