/**
 * Every query key in one place (docs/DESIGN_DECISIONS.md Q28, gap F16).
 *
 * Convention: `[<resource>, <scope>, …]` — the resource first, so a broad
 * `invalidateQueries({ queryKey: queryKeys.messages.all })` targets a whole
 * resource, followed by the narrowest scope that changes the response.
 * `messages.feed` is scoped by user id, so a second account can never read the
 * first account's cached feed.
 */
export const queryKeys = {
  messages: {
    all: ["messages"] as const,
    feed: (userId: number | null) => ["messages", "feed", userId] as const,
  },
  analytics: {
    all: ["analytics"] as const,
    dailySummary: ["analytics", "daily"] as const,
  },
} as const;
