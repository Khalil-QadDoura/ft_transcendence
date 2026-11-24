import { z } from "zod";
import { apiClient } from "../../api/client";
const coordinate = (limit: number) =>
  z
    .string()
    .trim()
    .min(1)
    .transform(Number)
    .pipe(z.number().finite().min(-limit).max(limit));
export const jobForm = z.object({
  title: z.string().trim().min(1).max(200),
  description: z.string().trim(),
  location: z.string().trim().max(150),
  latitude: coordinate(90),
  longitude: coordinate(180),
  status: z.enum(["draft", "open"]),
  salary_amount: z
    .string()
    .trim()
    .regex(/^(?:|\d{1,10}(?:\.\d{1,2})?)$/)
    .transform((v) => v || null),
  salary_currency: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^(?:|[A-Z]{3})$/)
    .transform((v) => v || null),
  salary_type: z.enum(["hourly", "daily", "weekly", "monthly"]),
  schedule: z.enum(["full_time", "part_time", "internship"]),
  urgency: z.enum(["normal", "urgent", "hot"]),
});
export type JobInput = z.output<typeof jobForm>;
export type OwnedJob = JobInput & {
  id: number;
  views_count: number;
  applications_count: number;
  new_applications_count: number;
  company_name: string | null;
};
export const employerApi = {
  list: (signal?: AbortSignal) =>
    apiClient<OwnedJob[]>("/jobs/mine", { signal }),
  save: (data: JobInput, id?: number) =>
    apiClient<OwnedJob>(id ? `/jobs/${id}` : "/jobs", {
      method: id ? "PATCH" : "POST",
      body: data,
    }),
  remove: (id: number) => apiClient<void>(`/jobs/${id}`, { method: "DELETE" }),
};
