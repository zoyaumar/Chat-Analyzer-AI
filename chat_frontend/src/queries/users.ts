import { useQueries } from "@tanstack/react-query";
import { getUserProfile } from "../api";
import { queryKeys } from "./keys";

/**
 * A name is stable for as long as the account exists, so one fetch per user id
 * is enough for a whole session.
 */
const PROFILE_STALE_TIME = 5 * 60 * 1000;

/**
 * Resolve message authors to usernames.
 *
 * `useQueries` rather than a hook per id: the number of authors on screen is
 * not known at render time, and a loop of `useQuery` calls would break the
 * rules of hooks. Each id gets its own cache entry, so two messages by the same
 * author cost one request, and a message that arrives over the socket is named
 * on the next render without any extra wiring.
 *
 * A profile that cannot be fetched — a deleted account, a 404 — simply stays
 * out of the map, and the caller falls back to `User <id>`.
 */
export function useUsernames(userIds: number[]): Record<number, string> {
  return useQueries({
    queries: userIds.map((userId) => ({
      queryKey: queryKeys.users.profile(userId),
      queryFn: () => getUserProfile(userId),
      staleTime: PROFILE_STALE_TIME,
      // One retry per id is plenty; a 404 is not going to become a 200.
      retry: false,
    })),
    combine: (results) => {
      const names: Record<number, string> = {};
      results.forEach((result, index) => {
        const userId = userIds[index];
        if (result.data && userId !== undefined) {
          names[userId] = result.data.username;
        }
      });
      return names;
    },
  });
}