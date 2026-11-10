import { QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";
import { createQueryClient } from "../api/client";

export const queryClient = createQueryClient();

export function Providers({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
