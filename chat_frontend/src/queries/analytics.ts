import { useMutation, useQuery } from "@tanstack/react-query";
import { analyzeSentiment, getDailySummary } from "../api";
import { queryKeys } from "./keys";

/**
 * `POST /analytics/sentiment` is a command — it runs a model on the text the
 * user typed — so it is a mutation: click-triggered, never fetched on mount and
 * deliberately not cached. Asking again means "analyze it again" (Q28/F16).
 */
export function useSentimentAnalysis() {
  return useMutation({ mutationFn: (text: string) => analyzeSentiment(text) });
}

/**
 * `GET /analytics/daily` is a read, so it is a cached query that the page
 * enables on the first "Get Daily Summary" click. Returning to `/analytics`
 * shows the last summary from the cache instead of an empty panel.
 */
export function useDailySummary(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.analytics.dailySummary,
    queryFn: getDailySummary,
    enabled,
  });
}
