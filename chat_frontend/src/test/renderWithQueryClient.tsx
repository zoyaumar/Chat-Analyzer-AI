import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";

/**
 * Test client for the TanStack Query migration (gap F16): no retries, so a
 * failing call surfaces immediately, and no cross-test cache because every
 * `renderWithQueryClient` call gets a fresh client.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

export function renderWithQueryClient(ui: ReactElement): RenderResult {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>{ui}</QueryClientProvider>
  );
}
