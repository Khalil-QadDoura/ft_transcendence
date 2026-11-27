import { useCallback, useSyncExternalStore } from "react";
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

  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (userId == null) return () => {};
      return store.subscribe(userId, () => {
        onStoreChange();
      });
    },
    [userId, store],
  );

  const getSnapshot = useCallback(() => {
    if (userId == null) return false;
    return store.getPresence(userId, initialOnline ?? false);
  }, [userId, initialOnline, store]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
