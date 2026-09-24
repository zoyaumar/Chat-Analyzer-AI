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
| `npm run test` | Vitest (jsdom) — auth guards, message merge, composer/delete UI, analytics, `fetch` client, query policy |

## Source layout

```
src/
├── api.ts                  # endpoint wrappers (plain data) + WebSocket connector
├── apiClient.ts            # typed fetch client: bearer token, query params, ApiError, 401 callback
├── apiClient.test.ts       # client tests with a stubbed fetch
├── messages.ts              # chronological, id-based REST/socket merge helper
├── messages.test.ts         # focused merge-helper tests
├── queries/                 # TanStack Query layer (gap F16)
│   ├── client.ts            # QueryClient: stale time, focus behaviour, retry predicate
│   ├── client.test.ts       # retry-policy tests
│   ├── keys.ts              # the `[<resource>, <scope>]` query-key convention
│   ├── messages.ts          # useMessageFeed / useSendMessage / useDeleteMessage / socket append
│   └── analytics.ts         # sentiment mutation + lazily enabled daily-summary query
├── types.ts                 # User, Message, pagination params, API response types
├── App.tsx                 # BrowserRouter + protected route table
├── main.tsx                # React root + QueryClientProvider
├── index.css               # `@import "tailwindcss";`
├── auth/                   # AuthProvider, RequireAuth, token helpers and tests
├── components/
│   ├── Navbar.tsx          # links + logout through AuthProvider
│   └── MessageList.tsx     # feed with loading/empty states, owner-only delete control
├── test/                   # Vitest setup + renderWithQueryClient helper
└── pages/
    ├── Login.tsx           # POST /users/login -> AuthProvider -> /chat
    ├── Register.tsx        # POST /users/register -> /login
    ├── Chat.tsx            # paginated feed, owner-only delete, composer, WebSocket connection
    ├── Chat.test.tsx       # delete, composer and load-older interaction tests
    ├── Analytics.tsx       # sentiment form + daily summary button
    └── Analytics.test.tsx  # sentiment result/error and daily-summary tests
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
`tailwind.config.js` and its CLI script are gone (gap **F7**) — add theme customisation to a CSS
`@theme` block in `src/index.css` instead.

## State & auth

- The JWT lives in `localStorage` under the key `token`.
- `apiClient.ts` is the whole HTTP layer: `apiGet`/`apiPost`/`apiDelete` over native `fetch`
  attach `Authorization: Bearer <token>`, build query strings, serialize JSON bodies (form-encoded
  for the login), return parsed JSON and throw a typed `ApiError` (`status`, plus the server's
  `detail`; `status` is `0` for a network failure). A non-login 401 notifies `AuthProvider`.
- `api.ts` maps endpoint calls onto that client and keeps the WebSocket connector: it owns the
  `before`/`before_id` query mapping for `MessagePageParams` and the owner-only delete call.
- `messages.ts` merges paginated REST results and socket frames by `id`, preserving chronological
  order so a message cannot appear twice when two delivery paths overlap.
- `queries/` is the server-state layer (TanStack Query 5, gap **F16**): `client.ts` sets the policy
  (30 s stale time, no focus refetch, two retries for network/`5xx` failures but none for `4xx`),
  `keys.ts` the `[<resource>, <scope>]` key convention (the feed is keyed by user id, so accounts
  never share cached messages), `messages.ts` the feed plus its mutations, and `analytics.ts` the
  analytics actions. Mutations write the cached feed directly instead of invalidating it, so loaded
  pages survive a send or a delete.
- `Chat.tsx` renders one `useMessageFeed()` object (messages, loading flag, "load older" cursor,
  error) and calls the send/delete mutations; `main.tsx` mounts the single `QueryClientProvider`.
- `AuthProvider` validates the token, owns the current user id, schedules expiry, registers the
  401 handler via `setUnauthorizedHandler` and clears it on sign-out; `RequireAuth` protects
  private routes.
- `Login.tsx` stores the token through the provider and shows a session-expired notice.
