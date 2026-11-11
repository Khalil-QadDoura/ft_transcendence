import type { FieldPath, FieldValues, UseFormSetError } from "react-hook-form";

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Returns false for non-validation errors and structured application guards.
 * The caller must handle those separately, rather than swallowing them.
 */
export function applyServerValidation<T extends FieldValues>(
  status: number,
  payload: unknown,
  fields: readonly FieldPath<T>[],
  setError: UseFormSetError<T>,
): boolean {
  if (
    status !== 422 ||
    !record(payload) ||
    !record(payload.error) ||
    payload.error.code !== "422" ||
    typeof payload.error.detail !== "string"
  )
    return false;
  const detail = payload.error.detail;
  const colon = detail.indexOf(":");
  const parts =
    colon < 0
      ? []
      : detail
          .slice(0, colon)
          .split("→")
          .map((part) => part.trim());
  const path = parts.slice(1).join(".");
  // Match against trusted form paths; never cast a server-supplied string to FieldPath.
  const field =
    parts[0] === "body" ? fields.find((name) => name === path) : undefined;
  setError(
    field ?? "root.server",
    {
      type: "server",
      message: "validation.server",
      types: { detail: field ? detail.slice(colon + 1).trim() : detail },
    },
    { shouldFocus: Boolean(field) },
  );
  return true;
}
