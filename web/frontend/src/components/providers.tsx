"use client";
import { ApiError } from "@/lib/api";
import { QueryClient,QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: (attempt, error) =>
              !(error instanceof ApiError && error.status === 401) &&
              attempt < 1,
            staleTime: 15000,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
