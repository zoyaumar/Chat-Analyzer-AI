import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { deleteMessage, getMessages, sendMessage } from "../api";
import { mergeMessages } from "../messages";
import type { Message, MessagePageParams } from "../types";
import { queryKeys } from "./keys";

/** Matches the backend maximum (`GET /messages/?limit=`, gap F6/B10). */
const PAGE_SIZE = 100;

const FIRST_PAGE: MessagePageParams = { limit: PAGE_SIZE };

type MessagePages = InfiniteData<Message[], MessagePageParams>;

/**
 * Cursor for the next (older) page: the **oldest** message of the last loaded
 * page — pages arrive in ascending order, so that is its first entry.
 */
function nextPageParams(lastPage: Message[]): MessagePageParams | undefined {
  const oldest = lastPage[0];
  if (!oldest || lastPage.length < PAGE_SIZE) return undefined;
  return { limit: PAGE_SIZE, before: oldest.timestamp, beforeId: oldest.id };
}

function updateFeedCache(
  queryClient: QueryClient,
  userId: number | null,
  update: (pages: Message[][]) => Message[][]
): void {
  queryClient.setQueryData<MessagePages>(queryKeys.messages.feed(userId), (current) =>
    current ? { ...current, pages: update(current.pages) } : current
  );
}

/**
 * Merge a new message into the newest page. The pages are cached oldest-last,
 * so growing the first page cannot disturb the pagination cursor, which is read
 * from the last page. `mergeMessages` de-duplicates by `id`, so the socket echo
 * of a message we just sent does not add a second copy (gap F6).
 */
function appendToNewestPage(pages: Message[][], message: Message): Message[][] {
  const [newest = [], ...older] = pages;
  const merged = mergeMessages(newest, [message]);
  if (merged.length === newest.length) return pages;
  return [merged, ...older];
}

/**
 * Bounded, keyset-paginated feed. Loading older messages is
 * `fetchNextPage()`; whether older messages exist is the library's
 * `hasNextPage`, derived from `nextPageParams`.
 */
export function useMessageFeed(userId: number | null) {
  const query = useInfiniteQuery({
    queryKey: queryKeys.messages.feed(userId),
    queryFn: ({ pageParam }) => getMessages(pageParam),
    initialPageParam: FIRST_PAGE,
    getNextPageParam: nextPageParams,
    enabled: userId !== null,
  });

  // The merge helper stays the single boundary between "pages plus socket
  // frames" and "one chronological list" (gap F6).
  const messages = useMemo(
    () => mergeMessages([], (query.data?.pages ?? []).flat()),
    [query.data]
  );

  return {
    messages,
    isLoading: query.isPending && query.fetchStatus !== "idle",
    hasOlderMessages: query.hasNextPage,
    isFetchingOlder: query.isFetchingNextPage,
    isOlderError: query.isFetchNextPageError,
    loadOlder: query.fetchNextPage,
    error: query.error,
  };
}

export function useSendMessage(userId: number | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (text: string) => sendMessage({ text }),
    onSuccess: (created) =>
      updateFeedCache(queryClient, userId, (pages) => appendToNewestPage(pages, created)),
  });
}

export function useDeleteMessage(userId: number | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (messageId: number) => deleteMessage(messageId),
    onSuccess: (_result, messageId) =>
      updateFeedCache(queryClient, userId, (pages) =>
        pages.map((page) => page.filter((message) => message.id !== messageId))
      ),
  });
}

/**
 * A socket frame arrives outside React's data flow, so it writes the cache
 * directly. When the realtime layer lands (M2, gaps B1/B12) this is the hook
 * the connection callback uses.
 */
export function useAppendSocketMessage(userId: number | null) {
  const queryClient = useQueryClient();

  return useCallback(
    (message: Message) =>
      updateFeedCache(queryClient, userId, (pages) => appendToNewestPage(pages, message)),
    [queryClient, userId]
  );
}
