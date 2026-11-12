/**
 * Conversations API Client (FE-29)
 */

import { apiClient } from "../../api/client";
import type { ConversationItem, UnreadSummary } from "./types";

/**
 * Fetch conversations for the current user ordered by updated_at descending.
 */
export async function listConversations(
  limit: number = 50,
): Promise<ConversationItem[]> {
  return await apiClient<ConversationItem[]>("/conversations", {
    method: "GET",
    params: { limit },
  });
}

/**
 * Get total unread messages count across all conversations.
 */
export async function getUnreadSummary(): Promise<UnreadSummary> {
  return await apiClient<UnreadSummary>("/conversations/unread", {
    method: "GET",
  });
}

/**
 * Get a single conversation with details and unread count.
 */
export async function getConversation(
  convId: number,
): Promise<ConversationItem> {
  return await apiClient<ConversationItem>(`/conversations/${convId}`, {
    method: "GET",
  });
}

/**
 * Create or retrieve an existing direct conversation with a peer.
 */
export async function createDirectConversation(
  peerUserId: number,
  jobId?: number,
): Promise<ConversationItem> {
  return await apiClient<ConversationItem>("/conversations", {
    method: "POST",
    body: {
      type: "direct",
      peer_user_id: peerUserId,
      job_id: jobId,
    },
  });
}
