/**
 * Types for Video Resume and Media Uploads (FE-25)
 */

export type ModerationStatus = "pending" | "approved" | "rejected";
export type LifecycleStatus = "loaded" | "posted" | "unposted" | "deleted";

export interface VideoUploadUrlIn {
  content_type?: string;
  ext?: string;
  expires_sec?: number;
}

export interface VideoUploadUrlOut {
  object_key: string;
  put_url: string;
  get_url: string;
  expires_sec: number;
  max_bytes: number;
}

export interface VideoConfirmIn {
  object_key: string;
  duration_sec: number;
  size_bytes: number;
  content_type: "video/mp4";
}

export interface VideoStatusOut {
  id: number;
  moderation_status: ModerationStatus | string;
  lifecycle_status: LifecycleStatus | string;
}

export interface MyVideoItem {
  id: number;
  object_key: string;
  duration_sec: number;
  size_bytes: number;
  content_type: string;
  moderation_status: ModerationStatus | string;
  lifecycle_status: LifecycleStatus | string;
  created_at: string;
  updated_at: string;
  signed_url: string;
  expires_sec: number;
}

export interface MyVideosOut {
  items: MyVideoItem[];
}

export type RecorderState =
  | "idle"
  | "requesting_permission"
  | "ready"
  | "recording"
  | "recorded"
  | "uploading"
  | "success"
  | "error";

export type VideoRecorderState = RecorderState;
