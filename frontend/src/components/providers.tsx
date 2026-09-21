"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // 계약 위반이나 없는 리소스를 재시도해봐야 같은 결과다.
            retry: (failureCount, error) => {
              if (error instanceof ApiError) {
                if (error.status === 404 || error.code === "contract_mismatch") return false;
              }
              return failureCount < 2;
            },
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
