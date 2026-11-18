import { z } from "zod";
import { apiClient } from "../../api/client";
import { createProfilePatchSchema } from "./schemas";

const profileSchema = z.object({
  id: z.number().int(),
  email: z.string(),
  is_email_verified: z.boolean(),
  first_name: z.string().nullable(),
  last_name: z.string().nullable(),
  position: z.string().nullable(),
  birth_date: z.string().nullable(),
  bio: z.string().nullable(),
  avatar_object_key: z.string().nullable(),
  avatar_url: z.string().nullable().optional(),
});
export type Profile = z.infer<typeof profileSchema>;
export type ProfilePatch = z.infer<ReturnType<typeof createProfilePatchSchema>>;
export const profileApi = {
  async get(signal?: AbortSignal) {
    return profileSchema.parse(await apiClient("/users/me", { signal }));
  },
  async patch(body: ProfilePatch) {
    return profileSchema.parse(
      await apiClient("/users/me", {
        method: "PATCH",
        body,
        signal: AbortSignal.timeout(15000),
      }),
    );
  },
};

export const profileFields = [
  "first_name",
  "last_name",
  "position",
  "birth_date",
  "bio",
] as const;
export type ProfileField = (typeof profileFields)[number];
export type ProfileValues = Record<ProfileField, string>;
export function profileValues(profile: Profile): ProfileValues {
  return Object.fromEntries(
    profileFields.map((key) => [key, profile[key] ?? ""]),
  ) as ProfileValues;
}
export function changedProfile(profile: Profile, values: ProfileValues) {
  const original = profileValues(profile);
  return Object.fromEntries(
    profileFields
      .filter((key) => values[key].trim() !== original[key])
      .map((key) => [key, values[key].trim()]),
  );
}
