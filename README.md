# Chat Analyzer AI

> A full-stack chat application with JWT authentication, real-time messaging over WebSockets, and NLP-powered analytics (per-message sentiment analysis and daily conversation summaries).

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.116-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy_2.0-async-D71F00?logo=sqlalchemy&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker_Compose-ready-2496ED?logo=docker&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)

**Status:** v0.2 — the core flows work end to end; the repo is mid-refactor towards a
one-command, test-covered, containerised release. See
[Milestones](#milestones--roadmap) for exactly what lands when, and
[`docs/GAPS_AND_IMPROVEMENTS.md`](docs/GAPS_AND_IMPROVEMENTS.md) for the itemised backlog.

---

## Table of contents

- [Overview](#overview)
- [Feature status](#feature-status)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Definition of shippable](#definition-of-shippable)
- [Environment variables](#environment-variables)
- [Database & migrations](#database--migrations)
- [API reference](#api-reference)
- [WebSocket protocol](#websocket-protocol)
- [Deployment](#deployment)
- [Testing & code quality](#testing--code-quality)
- [Milestones & roadmap](#milestones--roadmap)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Chat Analyzer AI is a monorepo containing a REST + WebSocket API and a single-page web
client. Users register, log in, exchange messages, and can run NLP analysis over their
conversation text.

The project is built around four ideas:

1. **A real backend, not a mock.** Passwords are argon2id-hashed (bcrypt hashes written before
   the migration still verify), every mutating endpoint is
   JWT-protected, and the schema is owned by Alembic migrations against PostgreSQL.
2. **Analytics as a first-class feature.** Message text can be scored for sentiment and
   aggregated into a daily summary, so the chat is more than a CRUD demo — and analysis is
   persisted rather than recomputed on every click.
3. **Realtime as a first-class transport.** A WebSocket channel carries new messages to
   every connected client; REST remains the source of truth for history.
4. **A shippable monorepo.** `docker compose up` should give you database, API and web
   client, with migrations applied automatically and a test suite guarding the auth and
   ownership rules.

## Feature status

Legend: ✅ works today · 🟡 works with caveats · 🔨 decided and scheduled, not built yet.

| Area | Feature | Status | Milestone |
| --- | --- | --- | --- |
| Auth | Registration with argon2id-hashed passwords (legacy bcrypt rehashed on login) | ✅ | — |
| Auth | Login → signed JWT (HS256, `PyJWT`, configurable lifetime) | ✅ | — |
| Auth | Bearer-token guard on protected endpoints | ✅ | — |
| Auth | `GET /users/me` profile lookup | ✅ | — |
| Auth | `GET /users/{user_id}` public profile (id, username, `created_at`) | ✅ | — |
| Auth | Account deletion (`DELETE /users/me`, messages cascade) | ✅ | — |
| Auth | Refresh tokens + server-side logout | 🔨 | M4 |
| Chat | Send a message (REST, persisted) | ✅ | — |
| Chat | List messages | ✅ auth-required, user-scoped, bounded keyset API with load-older UI | — |
| Chat | Delete your own message | ✅ owner-only control; confirmed deletion is removed from the feed | — |
| Chat | Author names in the feed (`GET /users/{user_id}`, cached per author, initials badge) | ✅ | — |
| Chat | Realtime delivery | 🟡 authenticated JSON echo only: no persistence, no fan-out — **deliberately kept and finished in M2** | M2 |
| Analytics | Sentiment analysis | ✅ scored once at write time and stored per message; ad-hoc repeats answered from a cache | — |
| Analytics | Daily summary | ✅ user-scoped UTC day window, chunked map-reduce summarisation, smaller pinned model | — |
| Analytics | Sentiment timeline (`GET /analytics/sentiment/timeline?days=N`) | ✅ daily counts and mean score, read from stored results | — |
| Data | Alembic as the single schema owner | ✅ real initial migration; `create_all()` removed; `alembic check` reports no drift | — |
| Data | Async database access (`asyncpg` + `AsyncSession`) | ✅ | — |
| Frontend | Login / register / chat / analytics screens, routing, logout | ✅ | — |
| Frontend | Single-origin API access (no CORS, no hard-coded URLs) | ✅ | — |
| Frontend | Protected routes + 401 handling and expiry UX | ✅ | — |
| Frontend | Loading, error and empty states | ✅ | M2 |
| Frontend | Visible keyboard focus, labelled feed, narrow-screen layout | ✅ | — |
| Ops | Docker Compose stack (`db` + `api` + `web`) | ✅ | — |
| Ops | Backend tests (pytest + httpx) and frontend tests (Vitest) | ✅ | — |
| Ops | CI on every push (lint, type-check, migrations, tests, `npm audit`) | ✅ | — |
| Ops | Dependency updates and CVE scanning (Dependabot + `pip-audit`) | ✅ | — |

> Every 🟡 and 🔨 row is tracked individually — with file references, impact and the fix — in
> [`docs/GAPS_AND_IMPROVEMENTS.md`](docs/GAPS_AND_IMPROVEMENTS.md). The reasoning behind each
> technology choice is in [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md).

## Architecture

```mermaid
flowchart LR
    subgraph Browser["Browser - React 19 + Vite"]
        UI["Pages: Login / Register / Chat / Analytics"]
        CL["api client - fetch + TanStack Query + AuthProvider"]
        WSC["WebSocket client"]
    end

    subgraph API["FastAPI application"]
        R_USERS["/users"]
        R_MSG["/messages"]
        R_ANA["/analytics"]
        R_WS["/ws/chat"]
        AUTH["auth_utils - PyJWT + pwdlib (argon2/bcrypt)"]
        ROUTES["route handlers / DB queries"]
    end

    subgraph Compose["docker compose"]
        DB[("PostgreSQL 16")]
        INF["inference service - M3; in-process today"]
    end

    ALEMBIC["Alembic migrations"]

    UI --> CL
    UI --> WSC
    CL -- "same origin: /users, /messages, /analytics" --> API
    WSC -- "same origin: /ws/chat, handshake auth" --> R_WS
    R_USERS --> AUTH
    R_MSG --> AUTH
    R_ANA --> AUTH
    R_USERS --> ROUTES
    R_MSG --> ROUTES
    R_ANA --> ROUTES
    ROUTES --> DB
    R_WS --> ROUTES
    R_ANA --> INF
    ALEMBIC --> DB
```

Request flow in words:

1. The SPA talks to **one origin**: the Vite dev server proxies to the API in development,
   and in the shipped Docker stack nginx serves the SPA and proxies API/WebSocket traffic. That
   removes CORS from the equation entirely (see gap S4).
2. The client stores the JWT and attaches it as `Authorization: Bearer <token>` on every
   request through the typed `fetch` wrapper (`src/apiClient.ts`).
3. Pages read server state through TanStack Query hooks in `src/queries/`: one cache and one
   query-key convention, retries for network failures, and mutations that write the cached feed
   directly instead of refetching it.
4. `POST /users/register` is checked against the credential policy, and both credential endpoints
   pass a per-client rate limit *before* anything is hashed or verified (`ratelimit.py`, gap S6).
5. FastAPI validates the token in `auth_utils`, resolves the current user, and hands the route
   an async `AsyncSession` through the `get_db` dependency.
6. Route handlers and WebSocket messages persist through a shared `crud.py` service layer (`create_message`, `get_messages_for_user`, `delete_message`). Both REST and WebSocket operations write messages identically and broadcast realtime frames via `realtime.manager.send_to_user`.
7. Analytics endpoints read the NLP layer's persisted results instead of recomputing them: each
   message is scored once at write time into `message_sentiment`, and the summary and timeline
   aggregate from there (gaps A3, A4, D7).

## Tech stack

Legend: **in use** today · **M1–M4** the milestone that introduces it · **open** not decided yet.

**Backend**

| Concern | Choice | Status |
| --- | --- | --- |
| Framework | FastAPI, routers split per resource; OpenAPI at `/docs` | in use |
| ORM | SQLAlchemy 2.0 — `AsyncSession` + `asyncpg` | ✅ async stack |
| Validation | Pydantic v2 (`from_attributes`) | in use |
| Auth | **PyJWT** (`HS256`) + argon2id password hashing via `pwdlib` (bcrypt verifies legacy hashes) | PyJWT ✅ (since M1) |
| Database | PostgreSQL 16 in Docker Compose, with a managed database optional for hosting | ✅ Compose for local development |
| Migrations | Alembic as the only writer of DDL | ✅ (`create_all()` removed) |
| Config | One `pydantic-settings` object reading `.env`, failing fast on missing secrets | ✅ |
| NLP | Distilled summariser + sentiment, lazy-loaded, results persisted | M3 (current pipelines are lazy-loaded; model/persistence work remains) |
| Packaging | `pyproject.toml` + a single pinned requirements file (`uv` optional) | ✅ |
| Server | Uvicorn | in use |
| Containers | Docker + Docker Compose (`db`, `api`, `web`; inference planned for M3) | ✅ |

**Frontend**

| Concern | Choice | Status |
| --- | --- | --- |
| Framework | React 19 + TypeScript 5.8 (strict, `noUnusedLocals`) | in use |
| Build tool | Vite 7 (`@vitejs/plugin-react`) | in use |
| Styling | Tailwind CSS 4 via the `@tailwindcss/vite` plugin | in use |
| Routing | React Router 7 (`BrowserRouter`) | in use |
| HTTP | native `fetch` behind a typed client (`src/apiClient.ts`); axios removed | ✅ (Q27/F14) |
| Server state | TanStack Query 5 (`src/queries/`) — cache, retries, mutations, loading/error state | ✅ (Q28/F16) |
| Same-origin access | Vite dev proxy + nginx `web` container in production | in place (hard-coded URLs removed) |
| Token parsing | `jwt-decode` for UI attribution | in use |
| Lint | ESLint 9 flat config (`typescript-eslint`, react-hooks, react-refresh) | in use |
| Tests | Vitest + React Testing Library + MSW | in use (70 tests: auth, chat UI, realtime socket hook, wire protocol, analytics, `fetch` client, query policy, MSW page-level, axe accessibility) |

## Repository layout

Entries marked **M2/M3** are the structure this repo is moving toward; the M1 runtime,
migration and container files are already present.

```
Chat-Analyzer-AI/
├── docker-compose.yml             # db + api + web, one published port (8080)
├── docker/
│   ├── api.Dockerfile             # migrations on start, then uvicorn
│   ├── web.Dockerfile             # builds the SPA, serves it through nginx
│   └── nginx.conf                 # SPA fallback, API/WS proxy, security headers
├── pyproject.toml                 # project metadata + tool config (ruff, pytest, mypy)
├── requirements.txt               # one pinned runtime list
├── .env.example                   # template for local configuration
├── .github/
│   ├── dependabot.yml             # weekly pip/npm/actions updates (O12)
│   └── workflows/ci.yml           # lint, type-check, audit, migrations, tests
├── alembic/
│   ├── env.py                     # async template, targets chat_backend.models.Base
│   └── versions/
│       ├── 06c1b9c7b0ec_...py     # true initial migration (users, messages)
│       ├── 1a2b3c4d5e6f_...py     # message query indexes
│       ├── f4e5d6c7b8a9_...py     # cap Message.text at 4000, cascade user deletion
│       ├── b7c8d9e0f1a2_...py     # row timestamps + message_sentiment (D5, D7)
│       └── c8d9e0f1a2b3_...py     # drop the redundant unique constraint on username
├── alembic.ini
├── chat_backend/                  # FastAPI application package
│   ├── main.py                    # app setup, router registration, health probes
│   ├── config.py                  # pydantic-settings: one place for every env var
│   ├── database.py                # async engine, AsyncSession factory, get_db dependency
│   ├── models.py                  # User, Message, MessageSentiment
│   ├── schemas.py                 # Pydantic v2 request/response models
│   ├── auth_utils.py              # password hashing, PyJWT encode/decode, get_current_user
│   ├── ai_utils.py                # lazy pinned pipelines, chunking, caching, model status
│   ├── crud.py                    # service layer shared by REST and the WebSocket handler
│   ├── realtime.py                # wire frames + the per-user connection registry
│   ├── ratelimit.py               # per-client sliding-window limiters + FastAPI dependencies (S6)
│   ├── observability.py           # JSON-lines logging + X-Request-ID middleware (O5)
│   └── routes/
│       ├── users.py               # register, login, /users/me, /users/{id}, delete me
│       ├── messages.py            # POST /messages/, GET /messages/, DELETE /messages/{id}
│       ├── analytics.py           # sentiment, daily summary, sentiment timeline
│       └── websocket.py           # WS /ws/chat — authenticated, persisted, broadcast
├── chat_frontend/                 # React + Vite SPA
│   ├── src/
│   │   ├── api.ts                 # endpoint wrappers (plain data), incl. GET /users/{id}
│   │   ├── apiClient.ts           # typed fetch client: bearer token, query params, ApiError
│   │   ├── realtime/              # useChatSocket + protocol: first-frame auth, heartbeat, reconnect
│   │   ├── queries/               # query keys, client policy, message/analytics/user hooks
│   │   ├── test/                  # Vitest setup, QueryClient render helper, MSW handlers
│   │   ├── types.ts               # shared TypeScript interfaces
│   │   ├── index.css              # Tailwind entry + the shared `.focus-ring` class
│   │   ├── auth/                  # AuthProvider, RequireAuth, token helpers
│   │   ├── components/            # Navbar, MessageList (author names + initials)
│   │   ├── pages/                 # Login, Register, Chat, Analytics
│   │   └── App.tsx                # BrowserRouter + protected route table
│   ├── index.html
│   ├── vite.config.ts             # dev proxy for the API and /ws, Vitest config
│   └── package.json
├── tests/                         # pytest + httpx suite (auth, limits, chat, analytics, AI, ops)
└── docs/
    ├── DESIGN_DECISIONS.md        # why each technology and pattern is here
    └── GAPS_AND_IMPROVEMENTS.md   # prioritised backlog with file references
```

## Getting started

### Option A — Docker Compose (the M1 target)

```bash
git clone https://github.com/zoyaumar/Chat-Analyzer-AI.git
cd Chat-Analyzer-AI
cp .env.example .env          # Windows: copy .env.example .env   (set SECRET_KEY)
docker compose up --build     # -> the whole app on http://localhost:8080
```

Three services, one published port:

| Service | Image / build | Purpose |
| --- | --- | --- |
| `db` | `postgres:16` | database with a named volume and a healthcheck |
| `api` | `docker/api.Dockerfile` | runs `alembic upgrade head`, then `uvicorn`; not published — only `web` reaches it |
| `web` | `docker/web.Dockerfile` | builds the SPA and serves it through nginx on `:8080`, proxying the API and `/ws` |

The browser therefore talks to one origin and there is no CORS configuration to get wrong.

> NLP inference still runs inside the `api` container (lazily, gap U4). The optional
> `inference` service — the same process split out, or a hosted API — is a decision that is
> still open; see **U4** in [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md).

### Option B — run the two halves directly (no Docker)

**Prerequisites**

| Tool | Version used |
| --- | --- |
| Python | 3.11+ (verified on 3.11.0) |
| Node.js | 20+ (verified on 22.13) |
| npm | 10+ |
| PostgreSQL | any reachable instance — the Compose `db` service, a local container on `5433` for tests, or a hosted instance such as Supabase |

**1. Configure**

```bash
cp .env.example .env        # then fill in DATABASE_URL and SECRET_KEY
```

**2. Backend**

```bash
py -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
py -m pip install -r requirements.txt

# run from the repository root: the package uses `chat_backend.` imports
uvicorn chat_backend.main:app --reload --port 8000
```

Interactive docs: <http://127.0.0.1:8000/docs> (click **Authorize** and paste the token from
`POST /users/login`). Readiness check: `curl http://127.0.0.1:8000/health/ready`.

**3. Frontend**

```bash
cd chat_frontend
npm install
npm run dev
```

Vite serves the SPA at <http://localhost:5173>. Register a user, log in, and you land on
`/chat`.

> **Current frontend auth path:** the SPA uses the Vite proxy in development and nginx in
> production; `AuthProvider` owns the token, guards private routes and handles expiry/401s.

### Useful commands

| Command | Where | Purpose |
| --- | --- | --- |
| `docker compose up --build` | repo root | full stack (M1) |
| `docker compose exec api alembic upgrade head` | repo root | apply migrations inside the stack (M1) |
| `uvicorn chat_backend.main:app --reload --port 8000` | repo root | run the API with autoreload |
| `alembic upgrade head` | repo root | apply migrations |
| `alembic check` | repo root | fail if the models and the migrations have drifted apart |
| `alembic revision --autogenerate -m "add x"` | repo root | generate a migration from model changes |
| `pytest` | repo root | backend tests (M1) |
| `RUN_AI_EVAL=1 pytest tests/test_ai_eval.py` | repo root | opt-in accuracy check on the pinned models — downloads the weights, fails if a model no longer clears the floor (A7) |
| `python -m pip_audit` | repo root | report known advisories in the installed Python packages (O12) |
| `npm run dev` | `chat_frontend/` | Vite dev server with HMR |
| `npm run build` | `chat_frontend/` | type-check (`tsc -b`) + production bundle |
| `npm run lint` | `chat_frontend/` | ESLint over the SPA |
| `npm audit --omit=dev --audit-level=high` | `chat_frontend/` | CVE gate for the production dependency tree (O12) |
| `npm test` | `chat_frontend/` | Vitest suite (70 tests across 12 files: auth, chat UI, realtime socket hook, wire protocol, analytics, `fetch` client, query policy, attribution, MSW page-level, CSP baseline, axe accessibility audits) |
| `py -m compileall chat_backend` | repo root | quick syntax check of the backend |

## Definition of shippable

M1 is the milestone that makes this repository something a stranger can run, trust and
deploy. It is done when all of the following are true:

- [x] `docker compose up` starts `db` + `api` + `web` from a clean clone, with migrations
      applied automatically and no manual steps beyond `.env`.
- [x] Register → login → send a message → see it in the feed works in the browser.
- [x] Every read is scoped to the authenticated user (no global message list, no global
      daily summary).
- [x] The schema is produced by Alembic alone in application startup; `alembic upgrade head`
      succeeds against an empty database and application code does not call `create_all()`.
- [x] The API refuses to start without `SECRET_KEY`, and token lifetime comes from config.
- [x] Registration enforces a credential policy and the endpoints that mint or create an identity
      are rate-limited per client address (gap S6).
- [x] One pinned dependency list installs a working environment from scratch.
- [x] `pytest` covers auth, message ownership, `/users/me` and the analytics scoping rule,
      and passes in CI.
- [x] `npm run lint && npm run build` pass in CI.
- [x] The README describes exactly what the code does — no aspirational setup steps.

## Environment variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | – | Async SQLAlchemy URL for PostgreSQL, e.g. `postgresql+asyncpg://…` (M1). |
| `DATABASE_URL_SYNC` | no | derived from `DATABASE_URL` | Sync URL (`postgresql+psycopg://…`) used only by Alembic, which runs migrations outside the async engine (M1). |
| `SECRET_KEY` | yes | – | HMAC key used to sign JWTs. There is no insecure fallback; startup fails when it is missing. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | `30` | Token lifetime, read through the settings object. |
| `DEBUG` | no | `false` | Sets the JSON log level to DEBUG (O5); it does not expose the removed `/test-db` route. |
| `DB_POOL_SIZE` | no | `5` | Base async SQLAlchemy pool size (D9). |
| `DB_MAX_OVERFLOW` | no | `10` | Connections allowed beyond `DB_POOL_SIZE` before the pool blocks (D9). |
| `DB_POOL_TIMEOUT` | no | `30` | Seconds to wait for a pooled connection before failing (D9). |
| `DB_POOL_RECYCLE` | no | `1800` | Seconds before an idle connection is recycled, ahead of a pooler dropping it (D9). |
| `AI_SENTIMENT_MODEL` | no | `distilbert-base-uncased-finetuned-sst-2-english` | Sentiment model (A7). |
| `AI_SENTIMENT_REVISION` | no | pinned 40-char SHA | Exact upstream revision of the sentiment model; empty means "follow the main branch" (A7). |
| `AI_SUMMARY_MODEL` | no | `sshleifer/distilbart-cnn-6-6` | Summarisation model (M3, replaces `facebook/bart-large-cnn`, A1). |
| `AI_SUMMARY_REVISION` | no | pinned 40-char SHA | Exact upstream revision of the summary model; empty means "follow the main branch" (A7). |
| `AI_INFERENCE_URL` | no | – | Base URL of a separate inference service (M3) — only relevant once the packaging decision (U4) is settled. |
| `LOGIN_RATE_LIMIT` | no | `10` | Login attempts allowed per client address per window before a `429` (S6). |
| `LOGIN_RATE_WINDOW_SECONDS` | no | `300` | Length of that window, in seconds (S6). |
| `REGISTER_RATE_LIMIT` | no | `5` | Registrations allowed per client address per window (S6). |
| `REGISTER_RATE_WINDOW_SECONDS` | no | `3600` | Length of that window, in seconds (S6). |
| `VITE_DEV_API_TARGET` | no | `http://127.0.0.1:8000` | Optional Vite dev-proxy target for the API. The browser still uses same-origin relative URLs. |

Example `.env` for the Docker stack:

```dotenv
DATABASE_URL=postgresql+asyncpg://app:app@db:5432/chat_analyzer
DATABASE_URL_SYNC=postgresql+psycopg://app:app@db:5432/chat_analyzer
SECRET_KEY=replace-with-a-long-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

Example `.env` for a hosted Postgres instance such as Supabase (note the driver and TLS
parameters — `asyncpg` takes `ssl=require` in the URL, not a `connect_args` dictionary):

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@<region>.pooler.supabase.com:5432/postgres?ssl=require
DATABASE_URL_SYNC=postgresql+psycopg://postgres.<project-ref>:<password>@<region>.pooler.supabase.com:5432/postgres?sslmode=require
SECRET_KEY=replace-with-a-long-random-string
```

> **Open decision.** Whether NLP inference stays inside the API process (lazily loaded, small
> model) or moves to its own container/hosted API is the one packaging question still open —
> see **U4** in [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md). Everything else about
> the AI layer is already decided: lazy loading, a smaller model, length guards, and persisted
> results.

## Database & migrations

Two tables, declared in `chat_backend/models.py`:

```
users                          messages
─────                          ────────
id            int PK           id         int PK
username      varchar UNIQUE   user_id    int FK -> users.id (not null)
password_hash varchar          text       varchar (not null)
                               timestamp  timestamptz default now()
```

`users 1 ──< messages` (SQLAlchemy `relationship(back_populates=...)`).

```bash
alembic upgrade head                              # apply the schema
alembic revision --autogenerate -m "add x"        # after changing models.py
```

**How the schema is managed:** Alembic is the only thing that writes DDL. The revision
`06c1b9c7b0ec` is a true `op.create_table(...)` initial migration, application startup does not
call `create_all()` (the test-only schema fixture may), and `alembic upgrade head` succeeds
against an empty database — verified against a fresh PostgreSQL 16 container, which is also what
the test suite runs on.

> **Note for the existing development database.** Because that database already had the
> tables (from the old `create_all()` era), stamp it once instead of upgrading:
> `alembic stamp head`. Fresh databases just need `alembic upgrade head` (gap **D11**).

Planned schema follow-ups: an explicit `ON DELETE` policy for `user_id` (D4)
and `created_at`/`updated_at` columns (D5). Indexes on `user_id`, `timestamp`,
and `(user_id, timestamp DESC)` are applied in migration `1a2b3c4d5e6f` (D3 ✅).

## API reference

Everything is served from one origin (see [Architecture](#architecture)); the examples below
use `http://127.0.0.1:8000` for the manual setup. Authenticated endpoints expect
`Authorization: Bearer <access_token>`. Browse the generated schema at `/docs` (Swagger UI),
`/redoc`, or `/openapi.json`.

### Users

| Method | Path | Auth | Request | Response |
| --- | --- | --- | --- | --- |
| `POST` | `/users/register` | – | JSON `{ "username": str, "password": str }` | `{ "id": int, "username": str, "created_at": str }` — `422` if the policy fails, `429` if the address is over its budget |
| `POST` | `/users/login` | – | `application/x-www-form-urlencoded` with `username`, `password` | `{ "access_token": str, "token_type": "bearer" }` |
| `GET` | `/users/me` | Bearer | – | `{ "id": int, "username": str, "created_at": str }` |
| `GET` | `/users/{user_id}` | Bearer | – | Same profile shape; used to name message authors (F10) |
| `DELETE` | `/users/me` | Bearer | – | `{ "detail": "Account deleted" }` — cascades the user's messages (D4) |

<details>
<summary>Register</summary>

```bash
curl -X POST http://127.0.0.1:8000/users/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "s3cret-pw"}'
# -> {"id": 1, "username": "alice", "created_at": "2026-02-11T09:14:02.881Z"}
```

Failure modes: `400 Username already registered`; `422` when the credential policy rejects the
input — `username` 3–32 characters of `[A-Za-z0-9._-]`, `password` at least 8 characters and at most
72 bytes (bcrypt hashes no more than that — the pre-S10 `passlib` stack truncated the rest
silently, and `bcrypt >= 4.1` now refuses longer input, which the login route answers as a `401`); `429 Too
many attempts` with a `Retry-After` header once this address has spent its registration budget
(S6, five per hour by default).
</details>

<details>
<summary>Login</summary>

```bash
curl -X POST http://127.0.0.1:8000/users/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice&password=s3cret-pw"
# -> {"access_token": "eyJhbGciOi...", "token_type": "bearer"}
```

Failure modes: `401 Invalid username or password` when the credentials are wrong or the account does
not exist; `429 Too many attempts` with a `Retry-After` header once this address has spent its login
budget (S6, ten per five minutes by default). Every attempt spends budget, so a password guesser
runs out — and so does a user who mistypes ten times, which is the trade-off that makes the limit
worth having.

The JWT payload is `{ "sub": "<user_id>", "exp": <unix ts> }`; M1 adds `iat`/`jti` so a
revocation list becomes possible later (gaps S7/Q9).
</details>

> `/users/me` returns the authenticated user's profile (`{id, username}`); the old
> response-validation 500 is fixed — gap **B2**, covered by `test_users_me_returns_profile`.

### Messages

| Method | Path | Auth | Request | Response |
| --- | --- | --- | --- | --- |
| `POST` | `/messages/` | Bearer | JSON `{ "text": str }` — the sender comes from the token | `Message` |
| `GET` | `/messages/` | Bearer | query `limit=1..100`, optional `before` + `before_id` cursor | `[Message]` |
| `DELETE` | `/messages/{message_id}` | Bearer | – | `{ "detail": "Message deleted" }` |

`Message` payload:

```json
{ "id": 12, "user_id": 1, "text": "hello world", "timestamp": "2026-02-11T18:03:41.991233+00:00" }
```

<details>
<summary>Send and list</summary>

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/users/login \
  -d "username=alice&password=s3cret" | jq -r .access_token)

curl -X POST http://127.0.0.1:8000/messages/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "first message"}'

curl "http://127.0.0.1:8000/messages/" -H "Authorization: Bearer $TOKEN"
```

Failure modes: `401` when the token is missing/expired; `404 Message not found or not yours`
when deleting someone else's message.
</details>

The current message API is protected and user-scoped. It supports bounded keyset pagination
(`before` + `before_id`) with a **Load older messages** control, merges REST and socket results
by `id`, and lets an owner delete their own message from the feed. The routes declare
response models (`MessageOut`), so the contract appears in OpenAPI, and the client never sends
a `user_id` that the API ignores.

### Analytics

| Method | Path | Auth | Request | Response |
| --- | --- | --- | --- | --- |
| `POST` | `/analytics/sentiment` | Bearer | JSON body `{ "text": "..." }` (max 4,000 characters) | `{ "label": "POSITIVE"\|"NEGATIVE", "score": float }` |
| `GET` | `/analytics/daily` | Bearer | – | `{ "date": "YYYY-MM-DD", "summary": str }` |
| `GET` | `/analytics/sentiment/timeline` | Bearer | query `days=1..365` (default 30) | `{ "days": int, "timeline": [{ "date", "messages", "positive", "negative", "avg_score" }] }` |

```bash
curl -X POST "http://127.0.0.1:8000/analytics/sentiment" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"I love this"}'
# -> {"label": "POSITIVE", "score": 0.9998}

curl http://127.0.0.1:8000/analytics/daily -H "Authorization: Bearer $TOKEN"
# -> {"date": "2026-02-11", "summary": "..."}

curl "http://127.0.0.1:8000/analytics/sentiment/timeline?days=7" -H "Authorization: Bearer $TOKEN"
# -> {"days": 7, "timeline": [{"date": "2026-02-10", "messages": 4, "positive": 3, "negative": 1, "avg_score": 0.82}]}
```

Current analytics behavior:

- Every message is scored once, at write time, in the same transaction, and the result is
  stored in `message_sentiment` with the model name and pinned revision that produced it
  (D7/A4/A7). Reads (the timeline) never run inference; a scoring failure costs the score,
  never the message (A6).
- `/analytics/sentiment` stays an ad-hoc endpoint for arbitrary text: `@lru_cache` answers
  repeats, the input is capped at 4,000 characters, and the model is asked with
  `truncation=True`, so a long input degrades instead of raising (A2).
- `/analytics/daily` is scoped to the authenticated user and summarises a half-open UTC day
  window; the transcript is chunked and summarised map-reduce style, so a busy day cannot
  exceed the model's token limit (A2).
- Both model-backed endpoints answer `503` with the reason when a model cannot load; chat,
  message history and deletion are unaffected. `GET /health/ready` reports each capability as
  `ready`, `failed` or `not_loaded`.

### Utility

| Method | Path | Auth | Response |
| --- | --- | --- | --- |
| `GET` | `/` | – | `{ "message": "Welcome to Chat Analyzer API with AI!" }` |
| `GET` | `/health` | – | `{ "status": "ok" }` |
| `GET` | `/health/ready` | – | `{ "status": "ok", "database": "up", "model_state": { "sentiment": "ready\|failed\|not_loaded", "summary": … } }` or `503` when the database is unavailable |

`/health` and `/health/ready` are the supported liveness/readiness probes; the public `/test-db`
  diagnostic has been removed (gaps **B8**, **O5**).

## WebSocket protocol

| Item | Value |
| --- | --- |
| Endpoint | `WS /ws/chat` (same origin — the Vite dev proxy forwards `/ws`) |
| Auth | first frame: `{"type": "auth", "token": "<jwt>"}` (RFC 6455 1008 if invalid/timed out) |
| Client → server | `{"type": "message", "text": "...", "client_id": "..."}` or `{"type": "ping"}` |
| Server → user sockets | `{"type": "message", "message": <MessageOut>, "client_id": "..."}`, `{"type": "message_deleted", "message_id": <id>, "user_id": <user_id>}`, `{"type": "pong"}` |

```ts
// chat_frontend/src/realtime/useChatSocket.ts
const { status, send } = useChatSocket({
  token,
  userId,
  onMessage: appendSocketMessage,
  onMessageDeleted: removeSocketMessage,
  sendOverHttp: (text) => sendOverHttp.mutateAsync(text),
});
```

Where it stands today, stated plainly:

- ✅ The handshake validates the JWT via first-frame auth — invalid/missing tokens receive close code 1008 (gaps **S1**, **S8**).
- ✅ Realtime wire protocol is typed and defensive (`parseFrame` drops unknown or non-object payloads) (gap **F3**).
- ✅ Messages sent over WebSocket persist into PostgreSQL via `crud.create_message` and broadcast to all active connections for that user with `client_id` echoed for sender reconciliation (gap **B1**).
- ✅ Deletion broadcasts (`message_deleted`) update loaded cache feeds across active tabs idempotently (gap **B1**).
- ✅ Reconnection with exponential backoff, ping/pong keepalive (25s interval, 10s timeout), and fallback to REST when disconnected or refused (gap **F11**).

Protocol details:

```jsonc
// client -> server (handshake)
{ "type": "auth", "token": "<jwt>" }

// server -> client (ack)
{ "type": "auth_ok", "user_id": 1 }

// client -> server (send)
{ "type": "message", "text": "hello", "client_id": "c1" }

// server -> author's connected sockets
{ "type": "message", "message": { "id": 13, "user_id": 1, "text": "hello", "timestamp": "2026-02-11T18:03:41Z" }, "client_id": "c1" }

// server -> author's connected sockets on deletion (HTTP or WS)
{ "type": "message_deleted", "message_id": 13, "user_id": 1 }
```

## Deployment

Containers are the deployment unit. The repo intentionally does **not** ship a
platform-specific blueprint: a Docker image is a portable contract — the same artefact runs
locally, in CI and on any host (see `docs/DESIGN_DECISIONS.md` Q32/Q41).

Planned deployment shape (M1):

```
client ──TLS──> reverse proxy ──> web (SPA assets)      # or api serves the bundle itself
                              └─> api (uvicorn)  ──> db (PostgreSQL)
                                     └─ migrations on start: alembic upgrade head
```

Requirements for any host:

| Requirement | Notes |
| --- | --- |
| PostgreSQL 16 (or a managed equivalent) | Only the API talks to it; `DATABASE_URL_SYNC` is used by migrations. |
| `SECRET_KEY` | Injected as a secret; never generated per deploy (so rolling out a new build must not log every user out). The app refuses to start without it (M1). |
| Environment variables | See [Environment variables](#environment-variables); nothing is baked into the image. |
| TLS termination | Any reverse proxy or load balancer; the API itself speaks plain HTTP. |
| Health probes | `/health` (liveness) and `/health/ready` (database + model readiness) in M1. |
| Structured logs | JSON lines on stdout, one object per line, correlated by `X-Request-ID` (O5). |
| Security headers | CSP, `nosniff`, frame/referrer policy and HSTS on API and SPA responses (S11); HSTS is ignored by browsers over plain HTTP until TLS terminates. |
| Persistent volume | Only if the NLP model cache lives in the container (M3 packaging decision). |

Any small VPS or container host with Compose installed is enough: `docker compose up -d --build`.

## Testing & code quality

| Check | Command | Status |
| --- | --- | --- |
| Frontend type-check + build | `cd chat_frontend && npm run build` | ✅ passes (`tsc -b && vite build`) |
| Frontend lint | `cd chat_frontend && npm run lint` | ✅ clean (`eslint .`, exit code 0) |
| Backend syntax | `py -m compileall chat_backend alembic tests` | ✅ passes |
| Backend tests | `py -m pytest` | ✅ 114 passing, 2 skipped (the opt-in A7 evaluation; needs a Postgres, see below) |
| Migrations against an empty database | `alembic upgrade head` + `alembic downgrade base` | ✅ verified on PostgreSQL 16, both directions |
| Models vs migrations | `alembic check` | ✅ no drift |
| Backend lint | `ruff check chat_backend tests alembic` | ✅ clean |
| Backend type-check | `mypy` | ✅ clean (non-strict + pydantic/SQLAlchemy plugins) |
| Frontend tests | `cd chat_frontend && npm test` | ✅ 70 passing (12 files) |
| Frontend production dependency audit | `cd chat_frontend && npm audit --omit=dev --audit-level=high` | ✅ 0 vulnerabilities |
| Python dependency audit | `python -m pip_audit` | 🟡 `transformers 4.53.0` only — 12 advisories, 9 with no fixed release upstream; everything else audits clean (D8/O12) |
| CI (all of the above on every push) | GitHub Actions | ✅ backend + frontend jobs |

**Backend test suite.** `tests/` covers register/login (happy path, duplicate username, wrong
password) and the hash migration itself (S10: a bcrypt hash written before the migration still
logs in and is rewritten to `$argon2id$`, a new account is argon2 from the start, and unusable
stored hashes answer `401` rather than `500`), the credential policy and its rate limits
(username shape, password length, the 72-byte
bcrypt cap, and a `429` with `Retry-After` per client address — `test_rate_limit.py`), `GET
/users/me` and `GET /users/{user_id}` (with/without token, safe projection), message
create/list/delete with ownership checks, analytics with fake models (no weights are
ever downloaded — `tests/conftest.py` replaces them session-wide), daily-summary user scoping,
the WebSocket accept/reject/echo paths, account deletion with its cascade, security headers, and
the structured-logging layer (JSON formatter, `X-Request-ID` echo, access-log correlation).
M3 added the AI-specific ones: scoring once at write time with the model name and revision
stored beside it, a scoring failure that costs only the score, chunking and memoisation unit
tests (`test_ai_utils.py`), the sentiment timeline (per UTC day, caller-scoped, window-bounded),
`503` instead of `500` when a model is unavailable, and the model state reported by
`/health/ready`. The suite runs against a real PostgreSQL — start a disposable one with:

```bash
docker run --rm -d --name chat-test-pg \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=chat_test -p 5433:5432 postgres:16
py -m pytest
```

`tests/conftest.py` points `DATABASE_URL` at `postgresql+asyncpg://…@127.0.0.1:5433/chat_test`
by default (override with `TEST_DATABASE_URL`), creates the schema from metadata, and
`TRUNCATE`s between tests.

**Frontend test suite.** Vitest + React Testing Library + jsdom cover unauthenticated route
redirects, valid-token access, token-expiry handling, REST/socket message de-duplication, the
owner-only delete and composer interactions, the analytics actions, the keyset "load older" cursor,
the `fetch` client (token header, query mapping, `ApiError`, 401 handler) and the TanStack Query
retry policy — 70 tests across 12 files, including the `useChatSocket` hook (heartbeat, backoff,
auth rejection, HTTP fallback), the defensive `parseFrame` protocol tests, MSW page-level tests
that run the real `apiClient`/query stack against `src/test/handlers.ts` (one of which asserts that
two messages from the same author cost exactly one profile request), the attribution and
accessibility contract of `MessageList`, the index.html CSP baseline, and the axe accessibility
audits (`src/test/a11y.test.tsx` over Login/Register/Analytics, plus the feed and whole-Chat-page
audits, with a negative test proving the audit still fails on broken markup). A dedicated
login-form test remains open.

A model is never loaded by either suite; the only place that touches real weights is
`RUN_AI_EVAL=1 pytest tests/test_ai_eval.py`, which is skipped by default.

## Milestones & roadmap

The backlog is ordered into milestones so that "shippable" has a definition instead of a vibe.

**M1 — Shippable core** (goal: a stranger can clone it, run it and trust it)

| Work | Gaps |
| --- | --- |
| ~~Migrate to async SQLAlchemy (`asyncpg`, `AsyncSession`, async `get_db`)~~ ✅ | B13 |
| ~~Single origin: Vite dev proxy + nginx `web` container; CORS wildcard removed~~ ✅ | S4, F2, F15 |
| ~~Fix the composer so Send actually posts~~ ✅ | F1 |
| ~~Scope messages and the daily summary to the authenticated user~~ ✅ | S2, S3 |
| ~~Fix `/users/me` and the `get_current_user` contract~~ ✅ | B2 |
| Replace `python-jose` with `PyJWT` ✅; add `iat`/`jti` | B14 ✅, S7 |
| ~~Alembic as the only schema owner; real initial migration; remove `create_all()`~~ ✅ | D1, D2, B9, D11 |
| ~~Message response models and bounded input~~ ✅ | B3 |
| ~~One settings object; fail fast without `SECRET_KEY`~~ ✅; honour `iat`/`jti` later | B6 ✅, S5 🟡 |
| ~~One pinned dependency list + `pyproject.toml` + `ruff` + `mypy`~~ ✅ | D8, T3 ✅, T4, A5 |
| Docker + Compose (`db`, `api`, `web`) with migrations on start ✅ | O13 ✅ |
| ~~Backend tests for auth, ownership and `/users/me`~~ ✅ (55 passing); CI on every push ✅ | T1 ✅, T5 ✅, O6 ✅ |
| ~~`/health` + `/health/ready`; retire the public `/test-db`; JSON logging + request ids~~ ✅ | B8 ✅, O5 ✅ |

**M2 — Realtime as a first-class channel**

| Work | Gaps |
| --- | --- |
| ~~WebSocket: authenticated handshake; move the token out of the query string~~ ✅ | S1, S8 ✅ |
| ~~Persist socket messages through the service layer and broadcast JSON~~ ✅ | B1, B12 ✅ |
| ~~Client: reconnect with backoff, connection state and defensive parsing~~ ✅ | F3, F11 ✅ |
| ~~Protected routes, 401 interceptor, expiry UX, `AuthProvider`~~ ✅ | F4, F5, Q29 |
| ~~Loading, error and empty states on every page~~ ✅ | F9 ✅ |
| ~~Typed `fetch` client replacing axios, with tests~~ ✅ | F14 ✅, Q27 |
| ~~TanStack Query for the server-state layer (keys, retries, mutations)~~ ✅ | F16 ✅, Q28 |
| ~~Keyset pagination, load-older UI, owner-only delete UI and `id`-based merge~~ ✅ | B10 ✅, F6 |
| ~~Security headers: strict CSP on API, Swagger exception, SPA meta + nginx set~~ ✅ | S11 ✅ |
| ~~`DELETE /users/me` with `ON DELETE CASCADE`; `Message.text` capped at 4000~~ ✅ | D4 ✅, D6 ✅ |
| ~~Pooling: pre-ping, recycle, env-tunable size/overflow/timeout~~ ✅ | D9 ✅ |
| ~~MSW handlers + page-level Chat tests over the real client stack~~ ✅ | T5 ✅, Q43 |
| ~~Frontend tests for auth, merge, delete/composer UI, analytics, socket hook, query policy, MSW page-level~~ ✅ (52 passing across 10 files) | T2 ✅ |

**M3 — AI, done right**

| Work | Gaps |
| --- | --- |
| ~~Lazy-load a small, pinned model and survive a failed download~~ ✅ | B5 ✅, A1 ✅, A6 ✅ |
| ~~Chunked map-reduce summarisation, length guards, `503`/`422` instead of `500`~~ ✅ | A2 ✅ |
| ~~Persist sentiment per message at write time; make analytics a lookup~~ ✅ | A4 ✅, D7 ✅ |
| ~~Pin model revisions; store model name/version with each result; opt-in accuracy fixtures~~ ✅ | A7 ✅ |
| ~~`GET /analytics/sentiment/timeline?days=N` over the stored scores~~ ✅ | A3 🟡 (dashboard still open) |
| ~~`created_at`/`updated_at` and UTC-grouped aggregates (`timestamptz` end to end)~~ ✅ | D5 ✅, D7 ✅ |
| ~~Author names in the feed from `GET /users/{user_id}`, cached per author~~ ✅ | F10 ✅ |
| ~~Focus rings, labelled feed, narrow-screen layout~~ ✅ | F12 ✅ |
| ~~Dependency updates and CVE scanning in CI~~ ✅ | O12 ✅ |
| Analytics dashboard with sentiment trends and volume charts | P12 |

**M4 — Hardening and product polish**

| Work | Gaps |
| --- | --- |
| Refresh tokens, server-side logout, `HttpOnly` cookie session | S7, Q5, Q9 |
| Password/username policy, rate limiting on login and register | S6 |
| Automated accessibility audit (axe) and Tailwind design tokens | F12 follow-up |
| Upgrade the Python pins that carry advisories (`transformers`, Starlette/FastAPI) | D8, O12 |
| Types generated from OpenAPI; delete dead files and template leftovers | F13 follow-up, F7, F8 |
| Redis pub/sub (or `LISTEN/NOTIFY`) for multi-instance fan-out | Q18 |
| All-users ("global") broadcast to every connected client, not only the author's sockets | P16 |
| Feature work: rooms/DMs, presence, typing indicators, read receipts, search, attachments | P1–P16 |

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/GAPS_AND_IMPROVEMENTS.md`](docs/GAPS_AND_IMPROVEMENTS.md) | Every known bug, missing feature and improvement, prioritised, with file references and the decision that closed it |
| [`docs/DESIGN_DECISIONS.md`](docs/DESIGN_DECISIONS.md) | "Why am I using X?" / "Should I use Y instead?" — the rationale, the alternatives and where each decision stands, plus the review dissent log |
| [`chat_frontend/README.md`](chat_frontend/README.md) | Frontend-specific setup notes and source map |

## Contributing

1. Branch from `main` (`git checkout -b feature/short-description`).
2. Keep the conventions: routers under `chat_backend/routes/`, Pydantic schemas in
   `schemas.py`, shared queries in `crud.py`, HTTP calls centralised in `src/api.ts` (wrappers) and
   `src/apiClient.ts` (transport), Tailwind
   utility classes inline.
3. Run the checks before opening a PR:

   ```bash
   py -m compileall chat_backend
   pytest                                   # M1
   cd chat_frontend && npm run lint && npm run build && npm test
   ```

4. Any model change ships with an Alembic revision that works against an empty database.
5. Describe the change and any follow-up work in the PR body.

Commit messages here are short and imperative (`Websockets`, `front end config`,
`Delete message endpoint`) — keeping that style makes the history easy to skim.

## License

No license file exists in this repository yet, so all rights reserved by the author. Add a
`LICENSE` (MIT and Apache-2.0 are the usual choices) before accepting external contributions.

