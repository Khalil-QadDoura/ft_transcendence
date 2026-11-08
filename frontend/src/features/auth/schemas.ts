import { z } from "zod";
import { text } from "../../lib/validation";

// Broad browser syntax check; Pydantic EmailStr remains authoritative.
const email = text(1)
  .trim()
  .pipe(z.email({ pattern: z.regexes.html5Email, error: "validation.email" }))
  .transform((value) => value.toLowerCase());
export const registerSchema = z.object({ email, password: text(8, 128) });
// BE-03 intentionally allows short login attempts; only registration has a minimum.
export const loginSchema = z.object({ email, password: text(0, 128) });
