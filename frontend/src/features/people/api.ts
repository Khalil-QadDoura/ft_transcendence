import { z } from "zod";
import { apiClient } from "../../api/client";

export const userId = z.coerce.number().int().positive().max(2147483647);
const person = z.object({
  id: userId,
  first_name: z.string().nullable(),
  last_name: z.string().nullable(),
  position: z.string().nullable(),
  bio: z.string().nullable(),
  avatar_url: z.string(),
  is_online: z.boolean(),
  friendship_status: z
    .enum(["pending_sent", "pending_received", "accepted"])
    .nullable(),
  // BE-22 must supply the relation ID; never substitute the user's ID.
  friendship_id: userId.nullable().optional(),
});
export type Person = z.infer<typeof person>;
export const peopleApi = {
  async profile(id: number, signal?: AbortSignal) {
    return person.parse(
      await apiClient(`/users/${userId.parse(id)}/profile`, { signal }),
    );
  },
  add: (id: number) =>
    apiClient("/friends/requests", {
      method: "POST",
      body: { addressee_id: userId.parse(id) },
    }),
  accept: (id: number) =>
    apiClient(`/friends/requests/${userId.parse(id)}/accept`, {
      method: "POST",
    }),
  decline: (id: number) =>
    apiClient(`/friends/requests/${userId.parse(id)}/decline`, {
      method: "POST",
    }),
  remove: (id: number) =>
    apiClient(`/friends/${userId.parse(id)}`, { method: "DELETE" }),
  async message(id: number) {
    return z.object({ id: userId }).parse(
      await apiClient("/conversations", {
        method: "POST",
        body: { peer_user_id: userId.parse(id) },
      }),
    );
  },
};
