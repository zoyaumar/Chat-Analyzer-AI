/**
 * MSW handlers mirroring the REST surface (gap T5).
 *
 * Page-level tests drive the real `apiClient` + TanStack Query stack against
 * these instead of `vi.mock`-ing `../api`, so query-string mapping, the bearer
 * header and cache updates are exercised end to end in jsdom.
 *
 * `mswState` is the two-way channel: seed it before rendering, inspect it (and
 * `feedRequests`) afterwards. Each test file owns its own `setupServer`, so
 * nothing here leaks between files.
 */
import { http, HttpResponse } from "msw";
import type { Message } from "../types";

export interface RecordedFeedRequest {
  searchParams: URLSearchParams;
  authHeader: string | null;
}

export const mswState = {
  /** What `GET /messages/` pages over, ascending by id like the database. */
  messages: [] as Message[],
  /** Every feed request the handler saw, oldest first. */
  feedRequests: [] as RecordedFeedRequest[],
  /** Every user id the feed asked a name for (gap F10), oldest first. */
  profileRequests: [] as number[],
};

let nextId = 1;

/** Reset the fixture; pass the messages a test wants to seed with. */
export function resetMswState(messages: Message[] = []): void {
  mswState.messages = [...messages].sort((a, b) => a.id - b.id);
  mswState.feedRequests = [];
  mswState.profileRequests = [];
  nextId = Math.max(0, ...messages.map((m) => m.id)) + 1;
}

/** A message whose id and timestamp both ascend with `offsetSeconds`. */
export function mswMessage(
  id: number,
  offsetSeconds: number,
  text = `Message ${id}`,
  userId = 1
): Message {
  return {
    id,
    user_id: userId,
    text,
    timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, offsetSeconds)).toISOString(),
  };
}

/** Usernames the profile endpoint knows; anything else is a 404 (gap F10). */
const knownUsernames: Record<number, string> = { 1: "alice", 2: "bob" };

export const handlers = [
  // Keyset pagination (B10): newest `limit` without a cursor, the page older
  // than `before_id` with one — ascending, like the API.
  http.get("/messages/", ({ request }) => {
    const url = new URL(request.url);
    mswState.feedRequests.push({
      searchParams: url.searchParams,
      authHeader: request.headers.get("Authorization"),
    });

    const limit = Number(url.searchParams.get("limit") ?? "100");
    const beforeId = url.searchParams.get("before_id");
    const ascending = [...mswState.messages].sort((a, b) => a.id - b.id);
    const page = beforeId
      ? ascending.filter((message) => message.id < Number(beforeId)).slice(-limit)
      : ascending.slice(-limit);
    return HttpResponse.json(page);
  }),

  http.post("/messages/", async ({ request }) => {
    const { text } = (await request.json()) as { text: string };
    const message: Message = {
      id: nextId++,
      user_id: 1,
      text,
      timestamp: new Date(Date.UTC(2026, 0, 2)).toISOString(),
    };
    mswState.messages = [...mswState.messages, message];
    return HttpResponse.json(message);
  }),

  http.delete("/messages/:id", ({ params }) => {
    const id = Number(params.id);
    mswState.messages = mswState.messages.filter((message) => message.id !== id);
    return HttpResponse.json({ detail: "Message deleted" });
  }),

  http.get("/users/me", () => HttpResponse.json({ id: 1, username: "alice" })),

  // Attribution (gap F10): a profile per author id, 404 for anyone unknown.
  http.get("/users/:id", ({ params }) => {
    const id = Number(params.id);
    mswState.profileRequests.push(id);
    const username = knownUsernames[id];
    if (!username) return new HttpResponse(null, { status: 404 });
    return HttpResponse.json({
      id,
      username,
      created_at: new Date(Date.UTC(2026, 0, 1)).toISOString(),
    });
  }),

  http.post("/users/register", () => HttpResponse.json({ id: 2, username: "newuser" })),

  http.post("/users/login", () =>
    HttpResponse.json({ access_token: "msw-token", token_type: "bearer" })
  ),

  http.post("/analytics/sentiment", () =>
    HttpResponse.json({ label: "POSITIVE", score: 0.99 })
  ),

  http.get("/analytics/daily", () =>
    HttpResponse.json({ date: "2026-09-25", summary: "Today was positive." })
  ),
];
