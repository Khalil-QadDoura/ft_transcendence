/**
 * Conversations API Client (FE-29)
 */

import { apiClient, getAccessToken } from "../../api/client";
import type {
  ConversationItem,
  EditMessagePayload,
  MessageItem,
  MessagesPage,
  SendMessagePayload,
  UnreadSummary,
} from "./types";

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

/**
 * Fetch messages for a conversation with cursor pagination.
 * Messages returned from backend are ordered oldest to newest.
 */
export async function listMessages(
  convId: number,
  beforeId?: number | null,
  limit: number = 50,
): Promise<MessagesPage> {
  const params: Record<string, string | number> = { limit };
  if (beforeId !== undefined && beforeId !== null) {
    params.before_id = beforeId;
  }
  return await apiClient<MessagesPage>(`/conversations/${convId}/messages`, {
    method: "GET",
    params,
  });
}

/**
 * Send a new message to a conversation with optional idempotency key.
 */
export async function sendMessage(
  convId: number,
  payload: SendMessagePayload,
): Promise<{ items: MessageItem[] }> {
  return await apiClient<{ items: MessageItem[] }>(
    `/conversations/${convId}/messages`,
    {
      method: "POST",
      body: payload,
    },
  );
}

/**
 * Edit an own message within 15 minutes of sending.
 */
export async function editMessage(
  convId: number,
  mid: number,
  payload: EditMessagePayload,
): Promise<MessageItem> {
  return await apiClient<MessageItem>(
    `/conversations/${convId}/messages/${mid}`,
    {
      method: "PATCH",
      body: payload,
    },
  );
}

/**
 * Soft delete an own message.
 */
export async function deleteMessage(
  convId: number,
  mid: number,
): Promise<void> {
  await apiClient<void>(`/conversations/${convId}/messages/${mid}`, {
    method: "DELETE",
  });
}

/**
 * Mark messages in a conversation as read up to last_message_id.
 */
export async function markAsRead(
  convId: number,
  lastMessageId: number,
): Promise<void> {
  await apiClient<void>(`/conversations/${convId}/read`, {
    method: "POST",
    body: { last_message_id: lastMessageId },
  });
}

/**
 * Synchronously extract the current authenticated user's ID from the JWT token.
 */
export function getCurrentUserId(): number | null {
  const token = getAccessToken();
  if (!token) return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join(""),
    );
    const parsed = JSON.parse(jsonPayload);
    const sub = Number(parsed.sub);
    return isNaN(sub) ? null : sub;
  } catch {
    return null;
  }
}
