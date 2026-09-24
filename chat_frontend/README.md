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
| `npm run tailwind:init` | Legacy Tailwind CLI helper; not needed with Tailwind 4 |

## Source layout

```
src/
├── api.ts                  # axios client + 401 callback, endpoint wrappers, WS connector
├── messages.ts              # chronological, id-based REST/socket merge helper
├── messages.test.ts         # focused merge-helper tests
├── types.ts                 # User, Message, pagination params, API response types
├── App.tsx                 # BrowserRouter + protected route table
├── main.tsx                # React root
├── index.css               # `@import "tailwindcss";`
├── auth/                   # AuthProvider, RequireAuth, token helpers and tests
├── components/
│   ├── Navbar.tsx          # links + logout through AuthProvider
│   └── MessageList.tsx     # currently empty — extract the message list from Chat.tsx here
├── pages/
│   ├── Login.tsx           # POST /users/login -> AuthProvider -> /chat
│   ├── Register.tsx        # POST /users/register -> /login
│   ├── Chat.tsx            # paginated feed, owner-only delete, composer, WebSocket connection
│   ├── Chat.test.tsx       # owner-only delete interaction test
│   └── Analytics.tsx       # sentiment form + daily summary button
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
`src/index.css` contains the single `@import "tailwindcss";` entry point.
`tailwind.config.js` is a leftover Tailwind 3 style config and is **not** read by Tailwind 4
— move any theme customisation into a CSS `@theme` block (gap **F7**).

## State & auth

- The JWT lives in `localStorage` under the key `token`.
- `api.ts` attaches it as `Authorization: Bearer <token>` via a request interceptor, maps
  `MessagePageParams` to the API's `before`/`before_id` query parameters, and exposes the
  owner-only delete call.
- `messages.ts` merges paginated REST results and socket frames by `id`, preserving chronological
  order so a message cannot appear twice when two delivery paths overlap.
- `AuthProvider` validates the token, owns the current user id, schedules expiry and handles
  non-login 401 responses; `RequireAuth` protects private routes.
- `Login.tsx` stores the token through the provider and shows a session-expired notice.
