import { act } from "react";
import { createRoot } from "react-dom/client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { expect, it, vi } from "vitest";
import { registerSchema } from "../features/auth/schemas";
import { validationOptions } from "./validation";
import { applyServerValidation } from "./server-validation";

const envelope = (detail: unknown) => ({ error: { code: "422", detail } });
it("allowlists nested paths and preserves colons in server messages", () => {
  const setError = vi.fn();
  applyServerValidation<{ profile: { name: string } }>(
    422,
    envelope("body → profile → name: Value error: required"),
    ["profile.name"],
    setError,
  );
  expect(setError).toHaveBeenCalledWith(
    "profile.name",
    {
      type: "server",
      message: "validation.server",
      types: { detail: "Value error: required" },
    },
    { shouldFocus: true },
  );
});
it.each([
  "body → __proto__: bad",
  "query → email: bad",
  "body → missing: bad",
  "invalid body",
])("keeps unmatched error at form level: %s", (detail) => {
  const setError = vi.fn();
  expect(
    applyServerValidation(422, envelope(detail), ["email"], setError),
  ).toBe(true);
  expect(setError.mock.calls[0][0]).toBe("root.server");
  expect(setError.mock.calls[0][1].types.detail).toBe(detail);
});
it("does not swallow transport failures or structured application guards", () => {
  const setError = vi.fn();
  for (const [status, payload] of [
    [500, envelope("failure")],
    [422, null],
    [422, envelope({ code: "profile_incomplete", next_step: "/profile" })],
  ] as const) {
    expect(applyServerValidation(status, payload, ["email"], setError)).toBe(
      false,
    );
  }
  expect(setError).not.toHaveBeenCalled();
});

it("runs Zod through RHF, then displays and focuses the matching server field", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const submitted = vi.fn();
  function Form() {
    const {
      register,
      handleSubmit,
      setError,
      formState: { errors },
    } = useForm({
      resolver: zodResolver(registerSchema, validationOptions),
      defaultValues: { email: "ana@example.com", password: "12345678" },
    });
    return (
      <form
        onSubmit={handleSubmit((values) => {
          submitted(values);
          applyServerValidation(
            422,
            envelope("body → email: Invalid email domain"),
            ["email", "password"],
            setError,
          );
        })}
      >
        <input aria-label="Email" {...register("email")} />
        <input aria-label="Password" {...register("password")} />
        <p role="alert">
          {errors.email?.message}: {String(errors.email?.types?.detail ?? "")}
        </p>
        <button>Submit</button>
      </form>
    );
  }
  try {
    await act(async () => root.render(<Form />));
    await act(async () =>
      host
        .querySelector("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        ),
    );
    expect(submitted).toHaveBeenCalledWith({
      email: "ana@example.com",
      password: "12345678",
    });
    expect(host.querySelector('[role="alert"]')?.textContent).toBe(
      "validation.server: Invalid email domain",
    );
    expect(document.activeElement).toBe(
      host.querySelector('input[aria-label="Email"]'),
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
