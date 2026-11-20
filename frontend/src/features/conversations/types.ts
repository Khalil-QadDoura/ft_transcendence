/**
 * Types for Direct Messages and Conversations (FE-29)
 */

export interface Participant {
  user_id: number;
  role: "admin" | "member";
  display_name?: string;
  avatar_url?: string | null;
  joined_at?: string;
}

export interface ConversationItem {
  id: number;
  type: "direct" | "ai" | string;
  title: string | null;
  job_id: number | null;
  job_title: string | null;
  last_message_id: number | null;
  last_message_content: string | null;
  last_message_author_id: number | null;
  unread_count: number;
  updated_at: string;
  peer?: {
    id: number;
    display_name: string;
    avatar_url: string | null;
  };
}

export interface UnreadSummary {
  total_unread: number;
}

export type MessageStatus =
  "sending" | "sent" | "delivered" | "read" | "failed";

export interface MessageItem {
  id: number;
  conversation_id: number;
  author_id: number | null;
  content: string;
  status: MessageStatus;
  message_type?: string;
  reply_to_id?: number | null;
  idempotency_key?: string | null;
  edited_at?: string | null;
  deleted_at?: string | null;
  created_at: string;
}

export interface MessagesPage {
  items: MessageItem[];
  prev_before_id: number | null;
}

export interface SendMessagePayload {
  content: string;
  reply_to_id?: number | null;
  idempotency_key?: string | null;
}

export interface EditMessagePayload {
  content: string;
}

export interface WsMessagePayload {
  id: number;
  conversation_id: number;
  author_id: number;
  content: string;
  status?: string;
  message_type?: string;
  reply_to_id?: number | null;
  idempotency_key?: string | null;
  edited_at?: string | null;
  deleted_at?: string | null;
  created_at: string;
}

export interface WsMessageUpdatedPayload {
  id: number;
  conversation_id: number;
  author_id: number;
  content: string;
  status?: string;
  edited_at: string;
}

export interface WsMessageDeletedPayload {
  id: number;
  conversation_id: number;
}

export interface WsMessageStatusPayload {
  message_id: number;
  status: "delivered" | "read";
}

export interface WsConversationUpdatedPayload {
  conversation_id: number;
  unread_count?: number | null;
}
