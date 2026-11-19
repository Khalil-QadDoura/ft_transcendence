import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type PropsWithChildren } from "react";
import { createQueryClient, onAuthChange } from "../api/client";
import { wsClient } from "../api/ws";
import { presenceStore } from "../features/presence";

export const queryClient = createQueryClient();

export function Providers({ children }: PropsWithChildren) {
  useEffect(() => {
    return onAuthChange((signedIn) => {
      if (signedIn) {
        wsClient.setQueryClient(queryClient);
        presenceStore.initWebSocketListener(wsClient);
        void presenceStore.fetchAndSeedFriends();
        void wsClient.connect();
      } else {
        wsClient.disconnect();
        presenceStore.reset();
      }
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
