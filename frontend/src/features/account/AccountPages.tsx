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
    message: "Passwords must match.",
  });
type PasswordFields = z.infer<typeof passwordSchema>;
function errorText(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 400)
      return typeof error.detail === "string"
        ? error.detail
        : "Please check your details and try again.";
    if (error.status === 429)
      return "Too many attempts. Please wait a few minutes and try again.";
    if (error.status === 422)
      return "Please check the form values and try again.";
  }
  return "We couldn’t complete that request. Please try again.";
}
export function ForgotPassword() {
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
        <p className="eyebrow">A WAY BACK IN</p>
        <h1>Forgot your password?</h1>
        <p>We’ll help you get back to your next chapter.</p>
      </div>
      <div className="account-panel">
        {sent ? (
          <div role="status">
            <h2>Check your inbox.</h2>
            <p>
              If this email has an eligible account, a reset link is on its way.
            </p>
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
              label="Email address"
              type="email"
              autoComplete="email"
              required
              {...register("email")}
              error={errors.email && "Enter a valid email address."}
            />
            {error && <p role="alert">{error}</p>}
            <Button type="submit" isLoading={isSubmitting}>
              Send reset link
            </Button>
          </form>
        )}
        <Link to="/login">Back to sign in</Link>
      </div>
    </section>
  );
}
function PasswordForm({ token }: { token?: string }) {
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
          label="Current password"
          type="password"
          autoComplete="current-password"
          required
          {...register("current_password")}
          error={errors.current_password && "Use no more than 128 characters."}
        />
      )}
      <Input
        label="New password"
        type="password"
        autoComplete="new-password"
        required
        {...register("new_password")}
        helperText="Use 8–128 characters."
        error={errors.new_password && "Use 8–128 characters."}
      />
      <Input
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        required
        {...register("confirm")}
        error={errors.confirm?.message}
      />
      {error && <p role="alert">{error}</p>}
      <Button type="submit" isLoading={isSubmitting}>
        {changing ? "Change password" : "Reset password"}
      </Button>
    </form>
  );
}
export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token");
  return (
    <section className="account-page">
      <div className="account-heading">
        <p className="eyebrow">A FRESH START</p>
        <h1>Choose a new password.</h1>
        <p>
          Your reset link works once. After resetting, sign in again on your
          devices.
        </p>
      </div>
      <div className="account-panel">
        {token ? (
          <PasswordForm key={token} token={token} />
        ) : (
          <p role="alert">
            This reset link is missing its token. Request a new link below.
          </p>
        )}
        <Link to="/forgot-password">Request a new reset link</Link>
      </div>
    </section>
  );
}
export function AccountSettings() {
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
        <p className="eyebrow">YOUR ACCOUNT, YOUR CHOICE</p>
        <h1>Account settings.</h1>
        <p>Keep your account secure and stay in control.</p>
        <Link to="/profile">Back to my profile</Link>
      </div>
      <div className="account-panel">
        <h2>Change password</h2>
        <p>
          This signs you out on all devices. You’ll sign in again with the new
          password.
        </p>
        <PasswordForm />
        <div className="account-danger">
          <h2>Delete account</h2>
          <p>
            Your account will be deactivated immediately and you won’t be able
            to sign in. Read the Privacy Policy for the retention and deletion
            details.
          </p>
          <Link to="/privacy">Privacy Policy</Link>
          <Button
            variant="danger"
            onClick={() => {
              setError("");
              setConfirm(true);
            }}
          >
            Delete account
          </Button>
        </div>
        <Modal
          isOpen={confirm}
          onClose={close}
          title="Delete your account?"
          description="This deactivates your account and ends your sessions. You won’t be able to sign in again."
          closeOnBackdrop={!removing}
        >
          {error && <p role="alert">{error}</p>}
          <div className="account-actions">
            <Button variant="outline" disabled={removing} onClick={close}>
              Keep my account
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
              Yes, delete my account
            </Button>
          </div>
        </Modal>
      </div>
    </section>
  );
}
