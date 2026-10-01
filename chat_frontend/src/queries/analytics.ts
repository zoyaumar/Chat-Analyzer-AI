import { useMutation, useQuery } from "@tanstack/react-query";
import { analyzeSentiment, getDailySummary, getSentimentTimeline } from "../api";
import { queryKeys } from "./keys";

/**
 * `POST /analytics/sentiment` is a command — it runs a model on the text the
 * user typed — so it is a mutation: click-triggered, never fetched on mount and
 * deliberately not cached. Asking again means "analyze it again".
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

/**
 * `GET /analytics/sentiment/timeline` is the trend view: a read of scores that
 * were already stored at write time, so it is a query rather than a mutation
 * and it costs the same whatever the models are doing.
 *
 * It is *not* gated behind a click the way the daily summary is. A chart with no
 * default render is a chart nobody sees, this read is cheap, and the API omits
 * empty days — so an account with no messages gets a real "nothing yet" answer
 * instead of a spinner.
 */
export function useSentimentTimeline(days: number) {
  return useQuery({
    queryKey: queryKeys.analytics.timeline(days),
    queryFn: () => getSentimentTimeline(days),
  });
}

