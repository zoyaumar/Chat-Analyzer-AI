import { QueryClient } from "@tanstack/react-query";
import { isApiError } from "../apiClient";

/** How many times a failed query is retried before the error reaches the UI. */
const MAX_RETRIES = 2;

/**
 * `retry` predicate for TanStack Query (docs/DESIGN_DECISIONS.md Q28, gap F16).
 *
 * A retry cannot fix a rejected request: `4xx` answers (401, 404, 422 …) are
 * final, so they surface immediately; network failures (status `0`) and `5xx`
 * are worth two more attempts. Mutations never retry — a repeated `POST` would
 * duplicate a message.
 */
export function shouldRetryRequest(failureCount: number, error: unknown): boolean {
  if (isApiError(error) && error.status >= 400 && error.status < 500) return false;
  return failureCount < MAX_RETRIES;
}

/**
 * The app's server-state policy.
 *
 * `staleTime` is short but non-zero so navigating between `/chat` and
 * `/analytics` reuses the cache instead of refetching the whole feed.
 * Focus refetching is off: the feed is paginated (a refetch walks every loaded
 * page) and realtime pushes arrive in M2 (gaps B1/B12). Mutations keep the
 * cache correct in the meantime (see `queries/messages.ts`).
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: shouldRetryRequest,
      },
      mutations: { retry: false },
    },
  });
}

/** One cache for the whole SPA; mounted in `main.tsx`. */
export const queryClient = createQueryClient();
