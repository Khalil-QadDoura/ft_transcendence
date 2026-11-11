import { z } from "zod";
import { choice, number, text } from "../../lib/validation";

// Editable fields only: BE-22 must settle reference `active` vs BE-02 `draft` status.
export const jobFieldsSchema = z.object({
  title: text(1, 200),
  description: text(),
  location: text(0, 150),
  latitude: number()
    .min(-90, "validation.latitude")
    .max(90, "validation.latitude"),
  longitude: number()
    .min(-180, "validation.longitude")
    .max(180, "validation.longitude"),
  salary_amount: number().min(0, "validation.salary").nullish(),
  salary_currency: z
    .string()
    .regex(/^[A-Z]{3}$/, "validation.currency")
    .nullish(),
  salary_type: choice([
    "hourly",
    "daily",
    "weekly",
    "monthly",
  ] as const).default("monthly"),
  schedule: choice(["full_time", "part_time", "internship"] as const).default(
    "full_time",
  ),
  urgency: choice(["normal", "urgent", "hot"] as const).default("normal"),
});
