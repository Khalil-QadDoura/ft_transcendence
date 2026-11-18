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

export interface WsMessagePayload {
  id: number;
  conversation_id: number;
  author_id: number;
  content: string;
  created_at: string;
  reply_to_id?: number | null;
}

export interface WsConversationUpdatedPayload {
  conversation_id: number;
  unread_count?: number | null;
}
