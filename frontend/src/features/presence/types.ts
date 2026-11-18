export interface PresenceEventPayload {
  user_id: number;
  is_online: boolean;
}

export type PresenceListener = (isOnline: boolean) => void;

export interface FriendPresenceItem {
  user_id: number;
  is_online?: boolean;
}

