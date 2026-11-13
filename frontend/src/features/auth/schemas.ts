import { z } from "zod";
import { text } from "../../lib/validation";

// Broad browser syntax check; Pydantic EmailStr remains authoritative.
const email = text(1)
  .trim()
  .pipe(z.email({ pattern: z.regexes.html5Email, error: "validation.email" }))
  .transform((value) => value.toLowerCase());
export const registerSchema = z.object({ email, password: text(8, 128) });
// Reject an empty browser submission; short nonempty passwords still reach BE-03.
export const loginSchema = z.object({ email, password: text(1, 128) });
