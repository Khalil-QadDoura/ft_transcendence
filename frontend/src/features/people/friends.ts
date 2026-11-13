import { z } from "zod";
import { apiClient } from "../../api/client";
import { userId } from "./api";
const friend = z.object({
  user_id: userId,
  first_name: z.string().nullable(),
  last_name: z.string().nullable(),
  position: z.string().nullable(),
  avatar_url: z.string(),
  is_online: z.boolean(),
  friendship_id: userId,
});
const request = z.object({
  id: userId,
  requester_id: userId,
  addressee_id: userId,
  status: z.string(),
});
export type Friend = z.infer<typeof friend>;
export type FriendRequest = z.infer<typeof request>;
export const friendsApi = {
  async list(signal?: AbortSignal) {
    return z.array(friend).parse(await apiClient("/friends", { signal }));
  },
  async requests(signal?: AbortSignal) {
    return z
      .array(request)
      .parse(await apiClient("/friends/requests", { signal }));
  },
};
