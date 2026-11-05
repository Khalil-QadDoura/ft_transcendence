import { z } from "zod";
export const credentials = z.object({
  email: z.email("Enter a valid email address."),
  password: z
    .string()
    .min(8, "Use at least 8 characters.")
    .max(128, "Use at most 128 characters."),
});
export const emailSchema = z.object({
  email: z.email("Enter a valid email address."),
});
export const profileSchema = z.object({
  first_name: z.string().trim().min(1, "This field is required.").max(50),
  last_name: z.string().trim().min(1, "This field is required.").max(50),
  position: z.string().trim().min(1, "This field is required.").max(100),
  bio: z.string().max(500),
  birth_date: z.string().refine((value) => {
    const d = new Date(value);
    const today = new Date();
    const age =
      today.getFullYear() -
      d.getUTCFullYear() -
      (today.getMonth() < d.getUTCMonth() ||
      (today.getMonth() === d.getUTCMonth() && today.getDate() < d.getUTCDate())
        ? 1
        : 0);
    return !Number.isNaN(d.getTime()) && age >= 18;
  }, "You must be at least 18 years old."),
});
