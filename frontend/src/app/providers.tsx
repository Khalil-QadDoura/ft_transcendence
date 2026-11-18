import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type PropsWithChildren } from "react";
import { createQueryClient, onAuthChange } from "../api/client";
import { wsClient } from "../api/ws";

export const queryClient = createQueryClient();

export function Providers({ children }: PropsWithChildren) {
  useEffect(() => {
    return onAuthChange((signedIn) => {
      if (signedIn) {
        wsClient.setQueryClient(queryClient);
        void wsClient.connect();
      } else {
        wsClient.disconnect();
      }
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
