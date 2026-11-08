import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
const client = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: false } },
});
export function Providers({ children }: PropsWithChildren) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
