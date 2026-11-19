import { useEffect, useState } from "react";
import { presenceStore, type PresenceStore } from "./presenceStore";

/**
 * React hook to observe real-time online status for a specific user.
 * Feeds from presenceStore (which is updated live via WebSocket "presence" events)
 * with initial fallback from REST data.
 */
export function useUserPresence(
  userId: number | null | undefined,
  initialOnline?: boolean,
  store: PresenceStore = presenceStore,
): boolean {
  // If initialOnline is provided and the store has no entry yet, seed it
  if (userId != null && initialOnline !== undefined) {
    store.seed(userId, initialOnline);
  }

  const [isOnline, setIsOnline] = useState<boolean>(() => {
    if (userId == null) return false;
    return store.getPresence(userId, initialOnline ?? false);
  });

  useEffect(() => {
    if (userId == null) {
      setIsOnline(false);
      return;
    }

    if (initialOnline !== undefined) {
      store.seed(userId, initialOnline);
      setIsOnline(store.getPresence(userId, initialOnline));
    }

    return store.subscribe(userId, (nextOnline) => {
      setIsOnline(nextOnline);
    });
  }, [userId, initialOnline, store]);

  return isOnline;
}
