# chat_frontend

Single-page client for Chat Analyzer AI. React 19 + TypeScript + Vite 7 + Tailwind CSS 4.

Setup, architecture and API details live in the [root README](../README.md); this file
covers only the frontend.

## Running locally

```bash
npm install
npm run dev        # http://localhost:5173
```

The backend must be running on `http://127.0.0.1:8000` — the base URL is currently
hard-coded in `src/api.ts` (`VITE_API_URL` is not read yet, see gap **F2** in
[`../docs/GAPS_AND_IMPROVEMENTS.md`](../docs/GAPS_AND_IMPROVEMENTS.md)).

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
├── api.ts                  # axios client + request interceptor, endpoint wrappers, WS connector (fetch in M2 — Q27/F14)
├── types.ts                # User, Message, TokenResponse, SentimentResult, SummaryResult
├── App.tsx                 # BrowserRouter route table
├── main.tsx                # React root
├── index.css               # `@import "tailwindcss";`
├── components/
│   ├── Navbar.tsx          # links + logout (clears the token)
│   └── MessageList.tsx     # currently empty — extract the message list from Chat.tsx here
└── pages/
    ├── Login.tsx           # POST /users/login -> localStorage token -> /chat
    ├── Register.tsx        # POST /users/register -> /login
    ├── Chat.tsx            # message feed, composer, WebSocket connection
    └── Analytics.tsx       # sentiment form + daily summary button
```

## Routing

| Path | Page | Guard |
| --- | --- | --- |
| `/`, `/login` | `Login` | – |
| `/register` | `Register` | – |
| `/chat` | `Chat` | none yet (gap **F4**) |
| `/analytics` | `Analytics` | none yet (gap **F4**) |

## Styling

Tailwind CSS 4 is wired through the `@tailwindcss/vite` plugin in `vite.config.ts`, and
`src/index.css` contains the single `@import "tailwindcss";` entry point.
`tailwind.config.js` is a leftover Tailwind 3 style config and is **not** read by Tailwind 4
— move any theme customisation into a CSS `@theme` block (gap **F7**).

## State & auth

- The JWT lives in `localStorage` under the key `token`.
- `api.ts` attaches it as `Authorization: Bearer <token>` via a request interceptor.
- `Chat.tsx` decodes `sub` with `jwt-decode` to learn the current user id.
- There is no 401 interceptor or token-expiry handling yet (gap **F5**).
