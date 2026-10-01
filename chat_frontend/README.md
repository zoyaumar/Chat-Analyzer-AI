# chat_frontend

Single-page client for Chat Analyzer AI. React 19 + TypeScript + Vite 7 + Tailwind CSS 4.

Setup, architecture and API details live in the [root README](../README.md); this file
covers only the frontend.

## Running locally

```bash
npm install
npm run dev        # http://localhost:5173
```

The backend must be running on `http://127.0.0.1:8000` for the Vite dev proxy. The browser
uses same-origin relative URLs; `VITE_DEV_API_TARGET` can override the proxy target in
`chat_frontend/.env` when the API runs elsewhere.

## Scripts

| Script | Description |
| --- | --- |
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | `tsc -b` type-check, then production bundle into `dist/` |
| `npm run preview` | Serve the built bundle locally |
| `npm run lint` | ESLint 9 (flat config) over the whole project |
| `npm run test` | Vitest (jsdom) — auth guards, token refresh, message merge, composer/delete UI, analytics, `fetch` client, query policy, realtime socket hook, wire protocol, MSW page-level Chat tests, CSP baseline, axe accessibility |

## Source layout

```
src/
├── api.ts                  # endpoint wrappers (plain data)
├── apiClient.ts            # typed fetch client: bearer token, query params, ApiError, 401 callback
├── apiClient.test.ts       # client tests with a stubbed fetch
├── messages.ts              # chronological, id-based REST/socket merge helper
├── messages.test.ts         # focused merge-helper tests
├── realtime/                # client end of /ws/chat
│   ├── protocol.ts          # chatSocketUrl, frame types, parseFrame, client ids, close codes
│   ├── protocol.test.ts     # defensive frame-parsing tests
│   ├── useChatSocket.ts     # react-use-websocket hook: first-frame auth, heartbeat, backoff, HTTP fallback
│   └── useChatSocket.test.ts # hook lifecycle tests
├── queries/                 # TanStack Query layer
│   ├── client.ts            # QueryClient: stale time, focus behaviour, retry predicate
│   ├── client.test.ts       # retry-policy tests
│   ├── keys.ts              # the `[<resource>, <scope>]` query-key convention
│   ├── messages.ts          # useMessageFeed / useSendMessage / useDeleteMessage / socket append
│   ├── analytics.ts         # sentiment mutation, daily summary, trend timeline query
│   └── users.ts             # useUsernames, batched author lookups cached per id
├── types.ts                 # User, Message, pagination params, API response types
├── App.tsx                 # BrowserRouter + protected route table
├── main.tsx                # React root + QueryClientProvider
├── index.css               # `@import "tailwindcss";`
├── auth/                   # AuthProvider, RequireAuth, token helpers and tests
│   ├── AuthContext.tsx     # session state, boot refresh, expiry renewal, logout
│   ├── context.ts          # the AuthContext value and its type
│   ├── useAuth.ts          # the `useAuth()` hook
│   ├── RequireAuth.tsx     # route guard; waits for `initialised` before deciding
│   └── token.ts            # in-memory access token + localStorage migration
├── components/
│   ├── Navbar.tsx          # links + logout through AuthProvider
│   └── MessageList.tsx     # feed with loading/empty states, owner-only delete control
├── test/                   # Vitest setup, renderWithQueryClient, MSW handlers, a11y helpers
│   ├── handlers.ts         # MSW route handlers for the page-level tests
│   ├── a11y.ts             # shared axe runner used by the audits
│   └── renderWithQueryClient.tsx
└── pages/
    ├── Login.tsx           # POST /users/login -> AuthProvider -> /chat
    ├── Register.tsx        # POST /users/register -> /login
    ├── Chat.tsx            # paginated feed, owner-only delete, composer, useChatSocket connection
    ├── Chat.test.tsx       # delete, composer, load-older and socket-fallback interaction tests
    ├── Chat.msw.test.tsx   # page-level tests over the real client stack via MSW
    ├── Analytics.tsx       # trend dashboard, sentiment form, daily summary button
    └── Analytics.test.tsx  # trend states, sentiment result/error, daily-summary tests
```

## Routing

| Path | Page | Guard |
| --- | --- | --- |
| `/`, `/login` | `Login` | – |
| `/register` | `Register` | – |
| `/chat` | `Chat` | `RequireAuth` |
| `/analytics` | `Analytics` | `RequireAuth` |

## Styling

Tailwind CSS 4 is wired through the `@tailwindcss/vite` plugin in `vite.config.ts`, and
`src/index.css` contains the single `@import "tailwindcss";` entry point. The Tailwind 3
`tailwind.config.js` and its CLI script are gone — add theme customisation to a CSS
`@theme` block in `src/index.css` instead.

## State & auth

- The access token lives in **memory only** (`src/auth/token.ts`); nothing JavaScript can
  read survives a reload. The durable half of the session is the rotating refresh token in
  an `HttpOnly` cookie — a legacy `localStorage` copy from an earlier release is adopted once on
  boot and deleted either way.
- `apiClient.ts` is the whole HTTP layer: `apiGet`/`apiPost`/`apiDelete` over native `fetch`
  attach `Authorization: Bearer <token>` (read from memory), build query strings, serialize
  JSON bodies (form-encoded for the login), return parsed JSON and throw a typed `ApiError`
  (`status`, plus the server's `detail`; `status` is `0` for a network failure). A non-login
  401 asks the registered session refresher once for a fresh token and replays the request;
  a 401 that survives that notifies `AuthProvider` and ends the session.
- `api.ts` maps endpoint calls onto that client: it owns the
  `before`/`before_id` query mapping for `MessagePageParams` and the owner-only delete call.
- `messages.ts` merges paginated REST results and socket frames by `id`, preserving chronological
  order so a message cannot appear twice when two delivery paths overlap.
- `queries/` is the server-state layer (TanStack Query 5): `client.ts` sets the policy
  (30 s stale time, no focus refetch, two retries for network/`5xx` failures but none for `4xx`),
  `keys.ts` the `[<resource>, <scope>]` key convention (the feed is keyed by user id, so accounts
  never share cached messages), `messages.ts` the feed plus its mutations, and `analytics.ts` the
  analytics actions. Mutations write the cached feed directly instead of invalidating it, so loaded
  pages survive a send or a delete.
- `Chat.tsx` renders one `useMessageFeed()` object (messages, loading flag, "load older" cursor,
  error) and calls the send/delete mutations; `main.tsx` mounts the single `QueryClientProvider`.
- `AuthProvider` validates the in-memory token, owns the current user id, runs the boot
  refresh (the refresh cookie is the only way in — `RequireAuth` waits for `initialised`, so
  there is no login flash), renews proactively at expiry, registers the 401 handler and the
  silent refresher via `setUnauthorizedHandler`/`setSessionRefresher`, and revokes the
  session server-side on sign-out; `RequireAuth` protects private routes.
- `Login.tsx` stores the token through the provider and shows a session-expired notice.
