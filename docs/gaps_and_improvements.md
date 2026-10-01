# Gaps, Bugs & Improvement Backlog

Everything that is missing, broken, fragile or simply worth improving in Chat Analyzer AI,
in one place.

**How this list was produced:** a static review of the project plus repeated verification of the
frontend build/lint, Python compilation, Docker Compose configuration, and the PostgreSQL-backed
pytest suite. Runtime behaviour that is not covered by the test suite remains explicitly marked
as unverified in the affected item.

**Decided direction (applied throughout this document):** async SQLAlchemy (`asyncpg` +
`AsyncSession`, gap **B13**); **PyJWT** instead of `python-jose` (**B14**); a `fetch`-based
API client instead of axios (**F14**); **TanStack Query** as the server-state layer (**F16**);
`pytest` + Vitest test suites with CI (**T1**, **T2**,
**T5**, **O6**); **Docker Compose** as the deployment unit (**O13**, gap **O8**); **no
Render/PaaS blueprint** (removed — **O1**, **O2**, **O9** are closed as obsolete); the
**WebSocket is kept** and finished rather than commented out or removed (**B1**, **S1**,
**F3**); shipping means `docker compose up` from a clean clone, not a PaaS deploy.

**ID scheme:** `S` security · `B` backend behaviour · `D` data layer · `F` frontend ·
`A` AI/analytics · `O` ops & repo hygiene · `T` testing · `P` product features ·
`N` NLP in production & deployment (runtime cost, cold start, memory, scale-out).

---

## Priority overview

| Tier | Meaning | Items |
| --- | --- | --- |
| **P0 — blocking** | The app looks like it works but does not; or it leaks data | *(none open — F1, S1, S2, S3, F3 fixed; O1, O2 retired with `render.yaml`)* |
| **P1 — shippable core (M1)** | The decided migrations and the fixes that make a clean clone runnable and trustworthy | D11 (reconcile the dev database with the migration history), O11 *(done: B2, B3, B4, B6, B7, B8, B9, B11, B13, B14, D1, D2, D8, D10, F1–F5, F15, O3, O5, O6, O8, O10, O13, S4, S5-code, T1, T2, T3, T4, T5, A5)* |
| **P2 — realtime + safety (M2)** | The WebSocket becomes a finished channel; auth hardening; robustness before wider use | *(none open — S8, S11, B1, B12, D4, D6, D9, F11, T5, D3, F9, F14, F16, B10, F3, F6 all fixed)* |
| **P3 — AI + quality polish (M3/M4)** | AI done right, finished UI, remaining hygiene and hardening | P12 (partly — the trend chart shipped) *(done: A1–A2, A4, A6, A7, B5, D5, D7, F7, F8, F10, F12, O4, O12, S6, S7, S9, S10, N1–N6)* |
| **P4 — product** | New features, not defects | P1–P17 |

Counts: 11 security · 14 backend · 11 data · 16 frontend · 7 AI · 13 ops (O1, O2, O9 closed as
obsolete with `render.yaml`; O7 never was a gap) · 5 testing · 16 product · 6 NLP-in-production
(N1–N6 ✅ fixed). `Q#` references elsewhere are decision IDs in
[`design_decisions.md`](design_decisions.md), not gap IDs.

---

## S — Security

### S1 — The WebSocket accepts anonymous clients; the JWT check is commented out ✅ fixed
**Where:** `chat_backend/routes/websocket.py`
**Impact:** High. `ws://…/ws/chat` was an open endpoint: the token in `?token=` was fetched but
never validated.
**Fix (done):** the handshake now decodes the JWT and closes with code `1008` when the token is
missing or invalid; the connection is registered through `realtime.manager`. Follow-ups completed:
the credential no longer travels in the query string (first-frame auth, S8 ✅), and REST plus the
socket share one code path through the `user_id_from_token` helper in `auth_utils`.

### S2 — `GET /messages/` is public and returns every user's messages ✅ fixed
**Where:** `chat_backend/routes/messages.py`
**Impact:** High. The endpoint had no `Depends(get_current_user)` and no `user_id` filter, so
anyone could download the global message table.
**Fix (done):** the route now requires the bearer token and filters
`models.Message.user_id == current_user`. Once rooms exist, filter by room membership instead.

### S3 — Daily summary aggregates all users' messages ✅ fixed
**Where:** `chat_backend/routes/analytics.py`
**Impact:** High. Tenant isolation was broken in the analytics path: a user's "daily summary"
was generated from everybody's text.
**Fix (done):** the query now filters `models.Message.user_id == current_user`. Still open:
cap how many messages are pulled into the summariser (A2).

### S4 — CORS is a wildcard combined with credentials ✅ fixed
**Where:** `chat_backend/main.py`
**Impact:** Was medium. The browser now uses one origin: Vite proxies development traffic and
nginx proxies production traffic, so CORS middleware is unnecessary.
**Fix (done):** removed `CORSMiddleware`; no wildcard origins or credentials flag remain.

### S5 — Weak default secret, and a live database password on disk 🟡 partially fixed
**Where:** `chat_backend/config.py`, `.env` (lines 2–3)
**Impact:** High. The `"supersecret"` fallback is **gone** — `Settings` has no default for
`secret_key`, so the app fails at startup when the env var is missing. Still open: the local
`.env` holds a real Supabase password in plaintext (correctly git-ignored, but on disk).
**Fix (remaining):** rotate the Supabase password, generate a 48-byte key, and enable secret
scanning (GitHub secret scanning / `gitleaks`) in CI.

### S6 — No password policy, no rate limiting, no brute-force protection ✅ fixed
**Where:** `chat_backend/schemas.py` (`UserCreate`), `chat_backend/routes/users.py`,
`chat_backend/ratelimit.py`, `chat_backend/config.py`
**Impact:** Was medium. `username: str` and `password: str` accepted a single character and any
Unicode; `/users/login` could be hammered without limit; registration was open to spam.
**Fix (done):** the policy lives on `UserCreate` — username 3–32 characters matching
`^[A-Za-z0-9._-]+$`, password at least 8 characters and at most 72 **bytes** — so a violation is a
`422` naming the field. The byte cap is a real bug fix rather than a style rule: bcrypt hashes at
most 72 bytes, where the old `passlib` stack truncated the rest silently — so `"x" * 80` and
`"x" * 72 + "yyyyyyyy"` were the same credential (reproduced against passlib 1.7.4 + bcrypt 4.0.1)
— and `bcrypt 5.0.0` refuses longer input outright (S10), which the login route turns into a
`401`.
The bounds sit on the request model only — `UserOut` inherits `UserBase`, and tightening a
*response* model would turn an account that predates the policy into a 500 — hence
`test_an_account_that_predates_the_policy_still_serialises`.

Rate limiting is a sliding-window counter per client address in `chat_backend/ratelimit.py`
(`slowapi` declined: a dependency for thirty lines — see Q50): `/users/login` 10 attempts / 5
minutes, `/users/register` 5 / hour, both env-tunable (`LOGIN_RATE_LIMIT`,
`LOGIN_RATE_WINDOW_SECONDS`, `REGISTER_RATE_LIMIT`, `REGISTER_RATE_WINDOW_SECONDS`) and separate
budgets so an exhausted login cannot block a signup. A refusal is `429` with `Retry-After`,
documented in `/docs` via `RATE_LIMIT_RESPONSES`. The bucket key is `X-Real-IP` (which nginx
rewrites, so it cannot be forged behind the Compose stack) falling back to the socket peer; the
table is capped and fails open. Covered by `tests/test_rate_limit.py` (the limiter with an injected
clock, plus the endpoints) and the policy cases in `tests/test_auth.py`.
**Remaining:** nothing for the CORS-free single-origin deployment. A second uvicorn worker multiplies
every limit, and an API exposed directly rather than through nginx can have `X-Real-IP` forged —
both are the shared-state question (**U8**), and the module docstring says so.

### S7 — Tokens cannot be revoked, and there is no refresh flow ✅ fixed
**Where:** `chat_backend/auth_utils.py`, `chat_backend/models.py`, `chat_backend/routes/users.py`
**Impact:** Was medium. The JWT carried only `sub` and `exp` — no `iat`, no `jti`, no refresh
token, no logout endpoint. Logging out (`Navbar.tsx`) only deleted the browser copy; the
token stayed valid until it expired.
**Fix (done):** the session is two halves. Access tokens carry `iat`/`jti` and stay short-lived
and stateless; the revocable half is a rotating refresh token — 32 random bytes, stored only
as a SHA-256 hash in the `refresh_tokens` table (migration `d3f7a1c9e2b4`, model with cascade
delete). `POST /users/refresh` rotates on every use (delete + reissue, so each token works
exactly once and a replayed copy finds no row), `POST /users/logout` deletes the row
server-side, and rows past `expires_at` are purged as they are encountered. The refresh
lifetime (`REFRESH_TOKEN_EXPIRE_DAYS`, default 14) sets the session's outer bound with
sliding renewal. Covered by ~10 tests in `tests/test_auth.py` (rotation, replay, logout
revocation, expiry purge) plus the SPA's silent-refresh tests.

### S8 — The WebSocket token travels in the query string ✅ fixed
**Where:** `chat_frontend/src/realtime/protocol.ts` (`chatSocketUrl`), `chat_backend/routes/websocket.py`
**Impact:** Was medium. Query strings land in access logs, proxies and browser history, so the
JWT was effectively logged.
**Fix (done):** the URL carries no credential at all — `chatSocketUrl()` builds
`ws(s)://<host>/ws/chat` from the page's own origin, and authentication happens via a dedicated
`{"type": "auth", "token": "..."}` first frame sent immediately upon opening. The server allows
up to 10 seconds (`AUTH_TIMEOUT_SECONDS = 10.0`) to receive this frame; if absent, invalid, or
expired, the connection is closed with RFC 6455 policy violation `1008` and never registered in the
broadcast pool. Tested in `tests/test_websocket.py` and `chat_frontend/src/realtime/protocol.test.ts`.

### S9 — Session token stored in `localStorage` ✅ fixed
**Where:** `chat_frontend/src/auth/token.ts`, `src/apiClient.ts`, `src/auth/AuthContext.tsx`
**Impact:** Was medium. Any XSS on the origin could exfiltrate the token, with no `HttpOnly`
fallback. Combined with `allow_origins=["*"]` (S4) the risk compounded.
**Fix (done):** the access token lives in **memory only** — nothing JavaScript-readable
survives a reload. The durable half of the session is the refresh token in an
`HttpOnly; SameSite=Strict; Path=/users` cookie (Q9/S7) the DOM never sees: `AuthProvider`
trades it for a fresh access token on boot, renews proactively at expiry, and a `401` gets one
silent refresh-and-replay before the session ends. The legacy `localStorage` copy is adopted
once and deleted either way, so browsers signed in under the old build migrate off the
XSS-readable storage on their first visit. The cookie's CSRF surface is met by
`SameSite=Strict` plus the explicit `Sec-Fetch-Site`/`Origin` guard (`require_same_origin`)
on login, refresh and logout; `Secure` follows `REFRESH_COOKIE_SECURE` (off on plain-HTTP
local dev, on behind TLS). Covered by `tests/test_auth.py` (cookie flags, origin rejection)
and `chat_frontend/src/auth/AuthContext.test.tsx` (boot refresh, no login flash, migration).

### S10 — The password-hashing stack is effectively unmaintained ✅ fixed
**Where:** `chat_backend/auth_utils.py`, `requirements.txt`
**Impact:** Was low-medium. `passlib` 1.7.4 (last release 2020) is used with modern `bcrypt`,
which triggers the well-known `AttributeError: module 'bcrypt' has no attribute
'__about__'` warning on some version pairs.
**Fix (done):** `passlib` is out of `requirements.txt`; `pwdlib` runs the hashers directly
(`PasswordHash((Argon2Hasher(), BcryptHasher()))`) — argon2id writes every password registered
from now on, and bcrypt stays only to verify hashes written before the migration, so no account is
locked out and no backfill script runs. `verify_and_rehash()` returns an upgraded hash whenever the
stored format is not the current one, and `POST /users/login` persists it on the login that proves
it — the rehash-on-successful-login plan from Q6/Q7. Hasher *refusals* answer `401` rather than
`500`: bcrypt 5.0.0 raises `ValueError` past 72 bytes instead of truncating, and `UnknownHashError`
covers a stored hash nothing can verify. The `bcrypt<4.1` stopgap retires with `passlib`; `bcrypt
5.0.0` and `argon2-cffi 25.1.0` are pinned directly. Five tests in `tests/test_auth.py` prove it:
a pre-migration bcrypt hash still logs in, the login that proves it rewrites the row to
`$argon2id$`, a new account is argon2 from the start, and both unusable-hash paths return `401`
rather than `500`.

### S11 — No XSS/CSP hardening on the SPA, no security headers on the API ✅ fixed
**Where:** `chat_frontend/index.html`, `docker/nginx.conf`, `chat_backend/main.py`
**Impact:** Was low-medium. Message text is rendered as text (React escapes it, so there is no
`dangerouslySetInnerHTML` hole today), but there was no `Content-Security-Policy`,
`X-Content-Type-Options`, `Referrer-Policy` or HSTS on either side.
**Fix (done):** the API sets `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy`, `Permissions-Policy`, HSTS and a CSP on every response —
locked to `default-src 'none'` for JSON, narrowed to the Swagger bundle's
origins on `/docs`/`/redoc`/`/openapi.json` so the UI still loads. The SPA
gets a CSP meta tag in `index.html` (the dev-time baseline; it keeps the Vite
React Refresh preamble alive) plus a stricter header set inside nginx's SPA
`location` — deliberately not at server level, so proxied API responses keep
only FastAPI's headers and Swagger's CSP is not intersected. Covered by
`tests/test_security_headers.py` and `src/test/indexHtml.test.ts`.

---

## B — Backend behaviour

### B1 — The WebSocket is an echo server, not a chat channel ✅ fixed
**Where:** `chat_backend/routes/websocket.py`, `chat_backend/realtime.py`, `chat_backend/crud.py`
**Impact:** Was high. `ConnectionManager` was unused, echoing raw text only to sender with no
persistence or fan-out.
**Fix (done):**
- Extracted shared message persistence into `chat_backend/crud.py` (`create_message`, `get_messages_for_user`, `delete_message`).
- Realtime registry and frame builders centralized in `chat_backend/realtime.py` with scoped per-user fan-out (`manager.send_to_user`).
- WebSocket handler authenticates via first-frame JWT, validates text via `schemas.MessageCreate` (max 4000 chars), persists via `crud.create_message`, and broadcasts standard `MessageOut` JSON payloads.
- REST routes (`POST /messages/`, `DELETE /messages/{id}`) fan out `message` and `message_deleted` frames through the same manager, ensuring parity between transports.
- Covered by unit tests in `tests/test_websocket.py` (isolation, fan-out, persistence, frame structure).

### B2 — `GET /users/me` cannot succeed ✅ fixed
**Where:** `chat_backend/auth_utils.py`, `chat_backend/routes/users.py`
**Impact:** Was high: `get_current_user` returned `int(user_id)` while the route declared
`response_model=schemas.UserOut`, so every call 500'd.
**Fix (done):** `get_current_user` now loads the `User` row and returns the ORM object; the
route serialises it through `UserOut`. Covered by `test_users_me_returns_profile`.

### B3 — Message endpoints have no response models and no input limits ✅ fixed
**Where:** `chat_backend/routes/messages.py`, `chat_backend/schemas.py`
**Impact:** Was medium: the public contract depended on ORM serialisation, and message text had no
  input limit.
**Fix (done):** create/list routes declare `MessageOut` response models, and `MessageCreate.text`
  is bounded to 4,000 characters. Regression coverage verifies oversized input returns `422`.

### B4 — Sentiment analysis accepts its input in a JSON body ✅ fixed
**Where:** `chat_backend/routes/analytics.py`, `chat_frontend/src/api.ts`
**Impact:** Was medium: `text` travelled on the URL, could reach proxy/server logs, and was
  limited by URL/proxy size rather than an explicit API contract.
**Fix (done):** the endpoint accepts a bounded JSON body (`{"text": …}`), the client posts JSON,
  and `SentimentResult` / `DailySummary` response models document the public contract.

### B5 — Both NLP models are loaded eagerly at import time 🟡 partially fixed
**Where:** `chat_backend/ai_utils.py`
**Impact:** Was high on any hosted tier: importing the module loaded ~1.6 GB of weights
before the app could serve a request, so a failed download or OOM took down login and chat.
**Fix (done):** each pipeline is loaded lazily on first use, behind a manual
double-checked lock (`lru_cache` would let two threads both miss and both download the
weights) and wrapped in `ModelUnavailableError` (A6), so importing the app touches no model
and a failed download degrades the analytics endpoints instead of the service. **Still open:**
packaging the weights for a deployment with no network (U4).

### B6 — Configuration is read inconsistently ✅ fixed
**Where:** `chat_backend/config.py`
**Impact:** Was medium: `SECRET_KEY` had an insecure fallback (S5), token lifetime was
hard-coded, and loading depended on import order.
**Fix (done):** one Pydantic `BaseSettings` class loads `.env` itself; `secret_key` and
`database_url` fail fast when absent, `access_token_expire_minutes` is configurable.
`iat`/`jti` and the refresh-token settings (S7/Q9) ship with the revocation flow.

### B7 — The "daily" filter mixes naive UTC datetimes with a timezone-aware column ✅ fixed
**Where:** `chat_backend/routes/analytics.py`
**Impact:** Was medium: a naive UTC date could be interpreted in the database session timezone,
  so "today" could silently mean a different calendar day.
**Fix (done):** timezone-aware UTC boundaries query the half-open interval
  `[start_of_day, start_of_next_day)`, alongside the user filter. The current contract is
  explicitly UTC; a user-local/IANA-timezone report can be added later if product needs it.

### B8 — Maintenance endpoints are public ✅ fixed
**Where:** `chat_backend/main.py`
**Impact:** Was low-medium. The public `/test-db` diagnostic was removed from the application.
**Fix (done):** `/health` and `/health/ready` are the supported probes; readiness checks the
configured database and returns `503` when it is unavailable.

### B9 — Side effects at import time ✅ fixed
**Where:** `chat_backend/database.py`, `chat_backend/main.py`
**Impact:** Was medium: database import-time checks and application-owned schema creation made
  Alembic history unreliable and coupled imports to a live database.
**Fix (done):** the module no longer opens a connection or calls `create_all()`; async engine
  creation is configuration-only, and the Compose API service runs `alembic upgrade head` before
  Uvicorn starts. Alembic is the only schema writer (D1/D2).

### B10 — Unbounded `limit` on the message list ✅ fixed
**Where:** `chat_backend/routes/messages.py`
**Impact:** Was low: `?limit=1000000` could attempt to serialise the entire table, and OFFSET
  pagination degrades as the table grows.
**Fix (done):** `limit` is constrained to `1..100`. The endpoint uses a keyset cursor over
  `(timestamp, id)`: `before` and `before_id` are supplied together to fetch the next older page,
  with timezone-aware timestamps required. Results are returned oldest-to-newest for the existing
  client contract.

### B11 — Dead imports, dead comments and a missing error handler in `main.py` ✅ fixed
**Where:** `chat_backend/main.py`
**Impact:** Was low, but it made the entry point hard to read and risked leaking exception details.
**Fix (done):** dead imports and commented blocks are gone; the application exception handler logs
  the traceback server-side and returns a generic `500` response. Health/readiness handlers are
  explicit and tested.

### B12 — `crud.py` is an empty placeholder ✅ fixed
**Where:** `chat_backend/crud.py`
**Impact:** Was low. Database logic lived inline in the routers, duplicating query logic and preventing reuse by the WebSocket handler.
**Fix (done):** implemented async `create_message`, `get_messages_for_user`, and `delete_message` in `crud.py`. Both `routes/messages.py` and `routes/websocket.py` now invoke these shared methods with active `AsyncSession`s, establishing a clean service layer. Tested in `tests/test_messages.py` and `tests/test_websocket.py`.

### B13 — Sync SQLAlchemy must become async (decided: `asyncpg` + `AsyncSession`) ✅ fixed
**Where:** `chat_backend/database.py`, every route handler, `alembic/env.py`
**Impact:** Was medium-high: a sync `SessionLocal` cannot serve the async M2 WebSocket
handler without blocking the event loop.
**Fix (done):** `asyncpg` + `AsyncSession`; `get_db` is an async generator; all handlers
`await execute/commit/refresh`; `DATABASE_URL=postgresql+asyncpg://…`; async-aware
`alembic/env.py`. Verified against PostgreSQL 16 by the test suite.

### B14 — `python-jose` must become PyJWT (decided) ✅ fixed
**Where:** `chat_backend/auth_utils.py`, `chat_backend/routes/websocket.py`, `requirements.txt`
**Impact:** Was low-medium: unused JOSE/JWE surface on the auth path.
**Fix (done):** PyJWT everywhere, `algorithms=["HS256"]` kept explicit, `jwt.InvalidTokenError`
catches bad tokens; covered by the auth and websocket tests. `iat`/`jti` remain for M4 (S7/Q9).

---

## D — Data layer, schema & migrations

### D1 — The checked-in Alembic revision assumes the tables already exist ✅ fixed
**Where:** `alembic/versions/06c1b9c7b0ec_create_users_and_messages_tables.py`
**Impact:** Was high for anyone cloning the repo: the alter-only revision failed on a fresh
database, forcing the `create_all()` workaround.
**Fix (done):** rewritten as a true initial migration (`op.create_table` for `users` and
`messages` + indexes). Verified with `alembic upgrade head` against an empty PostgreSQL 16
container (then reused by the test suite).

### D2 — The schema is owned by two tools at once ✅ fixed
**Where:** `chat_backend/main.py` vs `alembic/`
**Impact:** Was medium-high: `create_all()` ran on every app start and silently papered over
the broken migration (D1), so model changes could diverge from the migrated schema.
**Fix (done):** `create_all()` removed from `main.py`; `alembic upgrade head` is the only
schema writer (still needs to become a required deploy step when the container lands — O3).

### D3 — Missing indexes on the query paths that matter ✅ fixed
**Where:** `chat_backend/models.py`, `alembic/versions/1a2b3c4d5e6f_add_message_indexes.py`
**Impact:** Medium. Query paths filtering by `user_id` and sorting by `timestamp DESC` perform table scans without proper indexes.
**Fix (done):** added indexes on `messages.user_id`, `messages.timestamp`, and composite `ix_messages_user_id_timestamp_desc` with Alembic migration `1a2b3c4d5e6f`.

### D4 — Deleting a user is impossible, and the cascade was removed ✅ fixed
**Where:** `chat_backend/models.py`, `chat_backend/routes/users.py`,
`alembic/versions/f4e5d6c7b8a9_...py`
**Impact:** Was medium. The original foreign key was `ON DELETE CASCADE`; a migration dropped
that constraint and recreated it without `ondelete`, so orphaned messages would block a user
deletion and there is no account-deletion endpoint at all (GDPR/CCPA style "delete my data"
requests cannot be satisfied).
**Fix (done):** policy decided explicitly — messages die with their author (the
feed is author-scoped, so an orphaned message would be unreadable garbage): the
FK carries `ondelete="CASCADE"`, the relationship uses `passive_deletes=True`
(one `DELETE`, never a load-then-delete), and `DELETE /users/me` performs the
deletion — the issued token dies with the account because `get_current_user`
can no longer resolve it. Shipped in revision `f4e5d6c7b8a9`; covered by
`tests/test_account_deletion.py`, which checks the cascade against the real
schema.

### D5 — No `created_at` on users, no `updated_at` anywhere ✅ fixed
**Where:** `chat_backend/models.py`, `alembic/versions/b7c8d9e0f1a2_...py`
**Impact:** Low-medium. The `users` table lost its `created_at` column (dropped in the
migration, line 62), and nothing records when a message was edited.
**Fix (done):** `users.created_at` (server default `now()`) plus `users.updated_at` and
`messages.updated_at` (`onupdate=func.now()`), all `timestamptz`, added by migration
`b7c8d9e0f1a2_add_timestamps_and_persisted_message_sentiment`. `UserOut` exposes
`created_at`, so a client can date an account; nothing edits a message yet, so
`messages.updated_at` stays `NULL` until an edit endpoint exists — the column is the
bookkeeping this gap asked for, not a feature.

### D6 — `Message.text` has no length cap ✅ fixed
**Where:** `chat_backend/models.py`
**Impact:** Was low-medium. `Column(String)` became an unbounded `VARCHAR` in Postgres, so a
single client could store a multi-megabyte message (and then have every list request return
it).
**Fix (done):** `String(4000)` matches `MessageCreate.text`'s Pydantic
`max_length` (B3) at the schema level too; migration `f4e5d6c7b8a9` alters the
column (safe: every write was already capped by validation).

### D7 — Analytics results are computed on demand and never stored ✅ fixed
**Where:** `chat_backend/models.py`, `chat_backend/crud.py`, `chat_backend/routes/analytics.py`
**Impact:** Medium. Every sentiment request re-runs inference for text that may already have
been scored, and there is no model/version column, so results cannot be cached, charted over
time, or compared after a model upgrade.
**Fix (done):** `message_sentiment` (`message_id` PK, `label`, `score`, `model_name`,
`model_version`, `created_at`), written once per message in the same transaction as the
message (`crud.create_message`, both transports — gap B12) and cascaded away with it
(`ON DELETE CASCADE`). Scoring runs in a thread and is best-effort: a model that cannot load
costs the score, never the message (A6). `GET /analytics/sentiment/timeline` then reads the
table instead of running inference (A3/A4), and every row says which model and revision
produced it (A7). Migration: `b7c8d9e0f1a2`.

### D8 — Two divergent dependency files ✅ fixed
**Where:** `requirements.txt` (root)
**Impact:** Was medium: neither file was complete on its own and unpinned installs were not
reproducible.
**Fix (done):** single pinned `requirements.txt` (runtime + dev sections); `chat_backend/requirements.txt`
deleted; `--extra-index-url` for the CPU torch wheels sits at the top (A5); unused `supabase`
client dropped (Q11); `pyproject.toml` added for tool config (T3/T4).
**Remaining (see O12):** `pip-audit` finds advisories in the current pins —
`transformers==4.53.0` and `starlette==0.47.3` (pulled in by `fastapi==0.116.1`). Clearing them
means moving to `transformers` 5.x and a newer Starlette/FastAPI pair, so it belongs in one
upgrade batch with `RUN_AI_EVAL=1 pytest tests/test_ai_eval.py` (A7) as the accuracy check.

### D9 — Engine and pooling settings are left at defaults ✅ fixed
**Where:** `chat_backend/database.py`, `chat_backend/config.py`
**Impact:** Was low-medium. `create_async_engine(DATABASE_URL)` used default pooling with no
`pool_pre_ping`, `pool_recycle` or timeouts. Against a pooler, idle connections are recycled
server-side, producing the classic "server closed the connection unexpectedly" errors after
quiet periods.
**Fix (done):** `pool_pre_ping=True`, `pool_recycle=1800`, `pool_size=5`,
`max_overflow=10`, `pool_timeout=30` — all four knobs exposed as settings
(`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`) so a
hosted deployment tunes to its pooler without a code change. A serverless
deployment would swap in `poolclass=NullPool` instead (documented in place).

### D10 — `alembic/env.py` has duplicated configuration ✅ fixed
**Where:** `alembic/env.py`
**Impact:** Was low: `fileConfig` was called twice and stale comments obscured the file.
**Fix (done):** rewritten as a clean async template — one `fileConfig` call, settings-driven
URL with the `%` → `%%` escaping kept (a real gotcha worth the comment).

### D11 — The live database has no migration history
**Where:** development database vs `alembic/versions/06c1b9c7b0ec_...py`
**Impact:** High for adopting Alembic. Tables were created by `create_all()` (D2), so there is
no `alembic_version` row anywhere. Once a true initial migration exists (D1/Q13), running
`alembic upgrade head` against that database would try to create tables that already exist and
fail — the migration history has to be reconciled with reality once, explicitly.
**Fix:** rebuild development from the migration on a fresh container (the decided direction —
Q10 moves development to a local `db` service anyway), or `alembic stamp head` the existing
database if its data must be kept. Verify with `alembic upgrade head` against an empty
database in CI (O6) so this never silently regresses.

---

## F — Frontend

### F1 — The chat composer never sends anything ✅ fixed
**Where:** `chat_frontend/src/pages/Chat.tsx`
**Impact:** Was the highest-priority bug in the repo: two state variables (`text` bound to the
input, `input` used by `handleSend`) meant Send was a no-op.
**Fix (done):** one state variable (`input`) drives both the field and `handleSend`; the POST
response is appended to the list so the sent message appears without a reload. The client no
longer sends `user_id` — the server derives the sender from the token.

### F2 — API and WebSocket URLs are hard-coded; `VITE_API_URL` is ignored ✅ fixed
**Where:** `chat_frontend/src/api.ts`, `chat_frontend/vite.config.ts`
**Impact:** Was medium-high. The SPA now uses same-origin relative URLs in both environments.
**Fix (done):** `api.ts` uses `/`; Vite proxies API/WebSocket routes in development and nginx
proxies them in production. `VITE_DEV_API_TARGET` is the only development override.

### F3 — The WebSocket client parses every frame as JSON, but the server sends text ✅ fixed
**Where:** `chat_frontend/src/api.ts`, `chat_backend/routes/websocket.py`
**Impact:** High for the "realtime" story: the server sent `You said: hello`, the client ran
`JSON.parse` and threw on every frame.
**Fix (done):** the server now replies with JSON, and the client wraps the parse in
`try`/`catch` and only accepts frames that look like a `Message` (`id` + `text`), so a
malformed or echo frame can never break the UI. Full Message-shaped broadcast lands with B1.

### F4 — There are no protected routes ✅ fixed
**Where:** `chat_frontend/src/App.tsx`, `chat_frontend/src/auth/`
**Impact:** Was medium. Anonymous visitors could render the private chat and analytics screens.
**Fix (done):** `AuthProvider` validates the stored token, `RequireAuth` wraps `/chat` and
`/analytics`, and unauthenticated visitors are redirected to `/login` with the attempted path.

### F5 — No global 401 handling or token-expiry UX ✅ fixed
**Where:** `chat_frontend/src/apiClient.ts`, `chat_frontend/src/auth/`
**Impact:** Was medium. Expired or rejected sessions now have one predictable outcome.
**Fix (done):** the `fetch` client reports non-login 401s to `AuthProvider` (the login request opts
out via `skipUnauthorizedHandler`); the provider clears the stored token, redirects to `/login`, and
schedules expiry from the JWT `exp` claim. The login page shows a clear session-expired message.

### F6 — No delete UI or message de-duplication ✅ fixed
**Where:** `chat_frontend/src/api.ts`, `chat_frontend/src/messages.ts`, `chat_frontend/src/pages/Chat.tsx`
**Impact:** The initial feed loads bounded older pages, REST/socket results merge by `id`, and a
  message owner can delete their own message from the feed.
**Fix (done):** pagination uses `before` + `before_id`; `mergeMessages` keeps one copy by `id`
  in chronological order; the delete control calls `DELETE /messages/{id}` and removes the item
  only after success. The focused frontend tests cover de-duplication and the delete interaction.

### F7 — Dead Tailwind 3 configuration and unused build dependencies ✅ fixed
**Where:** `chat_frontend/tailwind.config.js`, `package.json`
**Impact:** Low-medium. Tailwind 4 is wired through `@tailwindcss/vite` and
`src/index.css`'s `@import "tailwindcss";`.
**Fix (done):** deleted `tailwind.config.js`, the `tailwind:init` script, and the unused
`@tailwindcss/postcss`, `postcss`, and `autoprefixer` devDependencies.

### F8 — Empty and leftover files, default Vite branding ✅ fixed
**Where:** `chat_frontend/src/components/MessageList.tsx`, `src/App.css`, `src/assets/react.svg`, `index.html`
**Impact:** Low, but an empty component file and Vite template leftovers look unfinished.
**Fix (done):** extracted `MessageList.tsx` from `Chat.tsx`, deleted unused `App.css` and `react.svg`, and set the document title to `Chat Analyzer AI`.

### F9 — No loading, error or empty states anywhere ✅ fixed
**Where:** `chat_frontend/src/pages/Login.tsx`, `Register.tsx`, `Chat.tsx`, `Analytics.tsx`, `src/components/MessageList.tsx`
**Impact:** Medium. Unhandled loading/error/empty states made user actions unresponsive or silent on failure.
**Fix (done):** added comprehensive loading, error, and empty states:
- `MessageList.tsx`: Added loading indicator and empty state ("No messages yet — say hello!").
- `Chat.tsx`: Added `isLoadingMessages`, `isSending`, error banner for load/send/delete failures, and disabled states during sending.
- `Login.tsx`: Added `loading` state on submit, distinct error messages for 400/401 vs 422 vs network/500 errors, and disabled button state.
- `Register.tsx`: Added `loading` state, surfaced server `detail` error message (e.g. username taken), and disabled button state.
- `Analytics.tsx`: Added separate loading and error states for Sentiment analysis and Daily Summary, input validation feedback, and disabled button states during requests.

### F10 — Messages show "User 3" instead of a name ✅ fixed
**Where:** `chat_frontend/src/pages/Chat.tsx` (line 78)
**Impact:** Low-medium usability. Only `user_id` is known client-side, so readers cannot tell
who wrote what. `MessageWithUser` exists in `schemas.py` but is unused, and there is no user
lookup endpoint.
**Fix (done):** `GET /users/{user_id}` returns the same safe projection as `/users/me`
(`UserOut`: id, username, created_at — never `password_hash`), and the feed resolves each
authorised author with `useUsernames` (`queries/users.ts`): one `useQueries` call per distinct
id, cached under `["users", "profile", <id>]`, so a message that arrives over the socket is
named on the next render. The feed shows `<username>:` (or `You:` for the reader), an
initials badge for other authors, and falls back to `User <id>` when a profile 404s.
`MessageWithUser` stays unused on purpose: returning it from `GET /messages/` would add a
join (and an N+1 risk) to the hot feed path for a name the client can cache itself.

### F11 — Socket lifecycle: double connections, no reconnect, no heartbeat ✅ fixed
**Where:** `chat_frontend/src/realtime/useChatSocket.ts`, `chat_frontend/src/realtime/protocol.ts`, `chat_frontend/src/pages/Chat.tsx`
**Impact:** Was medium. Socket lifecycle handling was fragile, with no reconnection backoff, no ping/pong keepalive, and double connection attempts in React StrictMode.
**Fix (done):**
- Replaced hand-rolled socket connection with `react-use-websocket` via custom hook `useChatSocket`.
- Structured wire protocol (`protocol.ts`) handles handshake (`auth`), messages, ping/pong heartbeats, error frames, and deletion notices defensively (`parseFrame` drops unknown/malformed shapes).
- Ping interval runs every 25s with 10s pong timeout detection, reconnecting dropped sockets automatically. Handshake rejections (code 1008) and user session mismatches (code 4001) abort reconnection permanently.
- `Chat.tsx` uses socket-first sending with seamless HTTP fallback when disconnected or unauthenticated. Unconfirmed socket sends trigger echo timeouts and leave composer text intact to prevent double submission.
- Fully tested across 13 hook unit tests in `src/realtime/useChatSocket.test.ts` and component tests in `src/pages/Chat.test.tsx`.

### F12 — No accessibility or responsive layout work ✅ fixed
**Where:** all pages/components, `chat_frontend/src/index.css`
**Impact:** The message feed had `role="log"` and `aria-live`, but labels, keyboard focus
states and narrow-screen layout were missing.
**Fix (done):** one `.focus-ring` component class (index.css) puts a visible `focus-visible`
ring on every control instead of repeating utilities; the feed is a named log
(`aria-label="Messages"`) that a keyboard can focus and scroll; the composer, navbar and page
shells reflow for narrow screens (`flex-col` → `sm:flex-row`, `h-64` → `sm:h-80`). Covered by
`MessageList.test.tsx` (labelled log, focusable, delete affordance) and the MSW page tests.
**Audit (done):** `axe-core` now audits every screen from the suite. `src/test/a11y.ts` exposes
`expectNoA11yViolations()` with the rule set pinned to WCAG 2.0/2.1 A + AA plus best-practice, and
`src/test/a11y.test.tsx`, `MessageList.test.tsx` and `Chat.test.tsx` run it over Login, Register,
Analytics, the feed and the whole Chat page (`document.body`, so page-level rules apply) — with a
negative test proving the audit still fails on an `img` without `alt` and a button without an
accessible name. The first run found a real defect: screen content sat outside any landmark, so
Login, Register, Chat and Analytics now wrap their screens in `<main>`. The Analytics
screen-reader pass gave both async results `role="status"` live regions (the sentiment one
announced by an sr-only "Sentiment:" prefix), re-homed the summary under an `h3`, and asserts the
`h1 → h2 → h3` heading hierarchy.

### F13 — Frontend types drift from the API ✅ fixed
**Where:** `chat_frontend/src/types.ts` vs `schemas.MessageOut`
**Impact:** Was medium: the client called the timestamp field `created_at` while the API returns
  `timestamp`.
**Fix (done):** the client type now uses `timestamp` and adds typed `MessagePageParams` for the
  keyset query. Generating the remaining types from OpenAPI is still a future improvement.

### F14 — The client uses axios where `fetch` would do ✅ fixed
**Where:** `chat_frontend/src/api.ts`, `chat_frontend/src/apiClient.ts`, `chat_frontend/package.json`
**Impact:** Was low-medium. axios shipped a request interceptor, `res.json()` and an error wrapper —
~13 kB gzipped (≈34 kB raw) for what the platform does natively.
**Fix (done, Q27):** `src/apiClient.ts` is now the whole HTTP layer: `apiGet`/`apiPost`/`apiDelete`
over native `fetch` attach the bearer token, serialize query params and JSON (or form-encoded login)
bodies, return parsed JSON and throw a typed `ApiError` carrying the server's `detail` (`status` is
`0` for a network failure, and `isUnauthorized` covers the 401 path). `src/api.ts` keeps the endpoint
wrappers and now returns plain data instead of axios response envelopes,
so pages call `getMessages()`/`loginUser()` directly (the WebSocket connector moved to
`src/realtime/`). `setUnauthorizedHandler` moved to the client
module and is still registered by `AuthProvider`; `axios` and its 23 transitive packages were removed
from `package.json`. `src/apiClient.test.ts` locks the token header, the `before_id` mapping, the
JSON/form bodies, the `ApiError` detail and the 401 handler (including the login exemption).

### F15 — The SPA and the API are not served from one origin ✅ fixed
**Where:** `chat_frontend/vite.config.ts`, `docker/nginx.conf`, `docker-compose.yml`
**Impact:** Was high for the shippable definition. The browser now has one origin in both modes.
**Fix (done):** Vite proxies API/WebSocket routes in development; nginx serves the built SPA
and proxies the same routes in production. `CORSMiddleware` and hard-coded client URLs are gone.

### F16 — No server-state layer (decided: TanStack Query) ✅ fixed
**Where:** `chat_frontend/src/queries/*`, `chat_frontend/src/pages/*.tsx`
**Impact:** Was medium. Every page hand-rolled loading/error/data state (F9 made it explicit), and
send/delete mutations had no shared cache-invalidation policy. The
explicit `id`-based merge helper solved delivery overlap but did not replace a query cache.
**Fix (done, Q28):** TanStack Query 5 owns server state, in a folder instead of inline effects.
`queries/client.ts` holds the policy — a 30 s stale time, focus refetching off (a refetch walks
every loaded page) and a `retry` predicate that retries network/`5xx` failures twice but never a
`4xx`. `queries/keys.ts` holds the `[<resource>, <scope>]` key convention, with the feed keyed by
user id so one account can never read another's cached messages. `queries/messages.ts` exposes
`useMessageFeed` (`useInfiniteQuery` over the keyset cursor, so the library's
`hasNextPage`/`isFetchingNextPage` replace the hand-rolled flags), plus `useSendMessage`,
`useDeleteMessage` and `useAppendSocketMessage` for the socket callback. Mutations write the cached
feed directly instead of invalidating it: the response (or the socket echo, de-duplicated by `id`)
is the authoritative row, while an invalidation would refetch every loaded page. `queries/analytics.ts`
keeps sentiment as a click-triggered mutation and turns the daily summary into a lazily enabled
query. `Chat.tsx` went from six pieces of manual state to one feed object; the F6 merge helper
remains the single explicit boundary between pages/socket frames and the rendered list.

---

## A — AI / analytics

### A1 — `bart-large-cnn` is the wrong model for a chat summary ✅ fixed
**Where:** `chat_backend/config.py`, `chat_backend/ai_utils.py`
**Impact:** Medium-high. BART-large is ~1.6 GB of weights and needs meaningful RAM per
request; summarising a chat transcript with it is both overkill and slow, and it makes a
free-tier deployment impossible.
**Fix (done):** the summariser is `sshleifer/distilbart-cnn-6-6` — the distilled model this gap
suggests, roughly a fifth of the weights — pinned to an exact revision (A7) and configurable
through `AI_SUMMARY_MODEL` / `AI_SUMMARY_REVISION`. Both models are still loaded lazily
(B5/A6), so nothing is downloaded until a summary or a score is actually needed. A hosted API
or an extractive summariser (Q: "Should I replace local transformers with a hosted LLM API?")
remains the alternative; the swap is now a settings change plus an evaluation run.

### A2 — Long inputs will hit the model's token limit and fail ✅ fixed
**Where:** `chat_backend/ai_utils.py`, `routes/analytics.py`
**Impact:** Medium-high. Every message for the day is concatenated into one string and passed
straight to BART, whose input limit is 1024 tokens. A busy day of chat produces a token-length
error that surfaces as a 500. The same applies to `analyze_sentiment` on a very long single
message.
**Fix (done):** `summarize_text` splits the text into 500-word chunks with a 50-word overlap,
summarises each, then folds the partial summaries until one pass fits (map-reduce; a short
tail joins its predecessor so no chunk is too small to summarise, and the fold is bounded and
finally truncated, so a model that never shortens cannot hang a request). A single message is
capped at validation (`MessageCreate`, 4000 characters, gap D6) and `analyze_sentiment` passes
`truncation=True, max_length=512`, so an oversized input degrades instead of raising. Covered
by `tests/test_ai_utils.py`.

### A3 — Analytics stop at single-message sentiment 🟡 partially fixed
**Where:** `chat_backend/routes/analytics.py`
**Impact:** Medium as a product gap. The "AI" in the project name meant two one-shot endpoints:
score one string, or summarise today. There was no sentiment *trend* over time.
**Fix (done):** `GET /analytics/sentiment/timeline?days=N` (1–365, default 30) returns one entry
per UTC day — message count, positive/negative counts and the mean score — oldest first, scoped
to the caller, read from `message_sentiment` rather than re-scored (A4). Days without activity
are omitted; messages whose scoring failed (A6) still count towards `messages` but not towards
the averages. Covered by `tests/test_timeline.py`.
**Remaining:** per-conversation aggregation, keyword/topic extraction and language detection. The
dashboard half of this gap has shipped (product gap P12): the Analytics page charts the timeline
over a 7/30/90-day window, with the figures repeated in a table. It is a pure SQL read, so it
inherits none of the runtime cost described in the **N** section.

### A4 — Sentiment is recomputed on every request ✅ fixed
**Where:** `chat_backend/crud.py`, `chat_backend/ai_utils.py`, `routes/analytics.py`
**Impact:** Medium. Inference ran on every call, including repeats of identical text, and
nothing was memoised (ties into D7).
**Fix (done):** all three suggestions. Messages are scored once at write time, in the same
transaction, and stored in `message_sentiment` (D7) — the analytics read path is a lookup, and
`tests/test_sentiment_persistence.py` fails if a read ever runs inference. Identical text in the
ad-hoc `/analytics/sentiment` endpoint is answered from an `lru_cache(maxsize=256)`, and the
cached dict is copied out so a caller cannot poison it. Scoring happens in a worker thread
(`asyncio.to_thread`) with the event loop free, and any failure costs the score, not the
message. A real queue stays out of scope until volume justifies it (Q23).

### A5 — The `torch` line in `requirements.txt` breaks dependency resolution ✅ fixed
**Where:** `requirements.txt` (root)
**Impact:** Was medium: a per-requirement `--index-url` switched pip's index for every line
after it.
**Fix (done):** `--extra-index-url https://download.pytorch.org/whl/cpu` now sits at the top
of the single pinned requirements file; PyPI stays primary and `torch==2.7.0` is pinned.

### A6 — No graceful degradation if a model fails to load ✅ fixed
**Where:** `chat_backend/ai_utils.py`, `routes/analytics.py`, `chat_backend/main.py`
**Impact:** Medium. If the model download fails (no network in the container, HF rate limit,
OOM), the import raises and the whole API fails to start — including chat, which has nothing to
do with AI.
**Fix (done):** importing the app touches no model. Each pipeline loads on first use behind a
lock (so two concurrent first requests cannot download it twice), and a failure is wrapped in
`ModelUnavailableError` and remembered, so the analytics endpoints answer `503` with the reason
while `/health/ready` reports `failed` per capability (`ready` / `failed` / `not_loaded`,
reported but never fatal — the probe stays `200`). The write path treats an unavailable model as
"no score today" and still stores the message, so sending, listing and deleting never touch a
model. Covered by `tests/test_model_unavailable.py`, `tests/test_ai_utils.py` and
`tests/test_health.py`.

### A7 — No model provenance or evaluation ✅ fixed
**Where:** `chat_backend/ai_utils.py`, `chat_backend/config.py`, `tests/test_ai_eval.py`
**Impact:** Low-medium. Neither pipeline pinned a revision, so "the same" input could produce
different output after an upstream model update, and there was no accuracy check.
**Fix (done):** both models load with an exact upstream revision
(`AI_SENTIMENT_REVISION`, `AI_SUMMARY_REVISION`; an empty value means "follow the main branch",
spelled out as `None` rather than passed through as an empty string). `sentiment_model_info()`
supplies the name and revision that are stored next to every score, so a row can always be
traced back to the weights that produced it. For drift, `tests/test_ai_eval.py` holds ten
obviously-labelled sentiment cases and two summarisation cases and asserts a floor (85 %
accuracy, summaries that are shorter but non-empty); it is opt-in — `RUN_AI_EVAL=1 pytest
tests/test_ai_eval.py` — because the suite itself must stay offline. Run it after bumping
`transformers`, `torch`, or a pinned revision: that is when a silent behaviour change would
otherwise ship.

---

## N — NLP in production & deployment

These are the items that stay invisible in `docker compose up` on a laptop and only bite once
the app runs somewhere real: a first request that times out, a container that is OOM-killed, a
model cache that re-downloads on every deploy, a second replica that quietly breaks fan-out.
Collected in a deployment review of the AI layer on `main` at `f7211ce`; every claim below is
read off the code named in **Where**, not inferred.

Read [How the NLP layer runs in a deployment](#how-the-nlp-layer-runs-in-a-deployment) first —
it explains the runtime shape these items are fixing.

### N1 — The daily summary runs a model on the event loop ✅ fixed
**Where:** `chat_backend/routes/analytics.py` — `daily_summary()`, the
`summary = await asyncio.to_thread(summarize_text, full_text)` call
**Impact:** High, and it gets worse as a day gets busier. `daily_summary` is an `async def`
route that calls the summariser **synchronously**. `summarize_text` → `_summarize_chunked` →
`_summarize_once` → `pipe(...)` is blocking CPU work, so for its whole duration the event loop
cannot serve anything else on that worker: no message sends, no WebSocket frames, no health
probes. A2 makes a busy day *several sequential model calls* — seconds, not milliseconds. One
user asking for their daily summary stalls the whole API for everyone.

This is an inconsistency, not a missing feature: the write path already does the right thing
(`crud._attach_sentiment` calls `asyncio.to_thread`, A4), and `POST /analytics/sentiment` is a
sync `def` route so FastAPI runs it in the threadpool. The daily summary is the one path that
does neither.

**Fix (done):** the route now calls `await asyncio.to_thread(summarize_text, full_text)`. The
existing `except ModelUnavailableError → 503` mapping is unchanged, since `to_thread` re-raises
the original exception. Covered by two new tests in `tests/test_model_unavailable.py`:
`test_daily_summary_does_not_block_the_event_loop` starts a deliberately slow summary, waits
until it is genuinely in flight, and asserts a `/health/ready` probe still answers inside two
seconds (on the old code the probe could not run at all), and
`test_daily_summary_still_503s_when_the_model_is_unavailable` pins the error mapping.

### N2 — Nothing warms the models, so the first request pays for the download ✅ fixed
**Where:** `chat_backend/main.py` (no `lifespan` / `on_event("startup")`),
`chat_backend/ai_utils.py` (`_load_pipeline`)
**Impact:** High for availability, invisible locally. Lazy loading is correct (A6: importing the
app must touch no model) but it means the **first** summary request downloads and initialises the
weights *inside that request*. On a cold container that is tens of seconds to minutes; a
30-second gateway timeout turns it into a user-visible 504 on a request that would have
succeeded a second later. On a host that sleeps between requests it repeats on every wake.

**Fix (done):** `ai_utils.warmup()` loads both pipelines and returns a per-capability state,
swallowing failures so a broken model cannot stop the other — or the caller. It is wired into a
`_lifespan` startup hook in `main.py` behind `AI_WARMUP_ON_STARTUP`, run through
`asyncio.to_thread` (it is the same blocking load a request would do, and boot is the one place
it may be waited on), and wrapped so even an unexpected error only logs. The setting defaults
**off** — right for a deployment, wrong for tests and quick restarts, which would otherwise pay a
model load they never use — and `docker-compose.yml` sets it to `true` for the `api` service.
Failures land in the existing `_LOAD_FAILURES`, so `/health/ready` reports them exactly as the
lazy path would. Covered by three tests in `tests/test_model_unavailable.py`, including one that
pins the off-by-default behaviour.

### N3 — The model cache is not on a volume, so every deploy re-downloads the weights ✅ fixed
**Where:** `docker-compose.yml` (the only volume declared is `pgdata`), `docker/api.Dockerfile`
**Impact:** High for deploy time and egress, and it compounds N2. HuggingFace caches to
`~/.cache/huggingface` *inside the container filesystem*. Nothing in the image pre-fetches the
models, and no volume is mounted over that path, so a `docker compose up --build`, a redeploy or
an autoscaled pod **re-downloads both models from the hub every single time**.

**Fix (done):** the `api` service mounts a named `huggingface` volume at
`/cache/huggingface` and sets `HF_HOME` to that path, so the first boot populates the cache and
every later boot reuses it — the download leaves the deploy path entirely after the first run.
A build-time prefetch (`RUN python -c "..."` in the Dockerfile) was the alternative and was
rejected: it makes the image much larger for the same benefit, and the volume also survives
`docker compose down`. `docker compose config` was used to confirm the volume and the variable
resolve as intended.

### N4 — The API container carries both models plus torch, with no memory budget ✅ fixed
**Where:** `docker-compose.yml` (`api` service — no `deploy.resources` / `mem_limit`),
`requirements.txt` (`torch==2.7.0` CPU wheel, `transformers==4.53.0`)
**Impact:** High, and it is the reason the API cannot scale out. With inference in-process, the
`api` container holds the sentiment model *and* the summariser resident for the life of the
process, plus torch. A modest `api` container will be OOM-killed under this, and because it
surfaces as a restart loop rather than a clean error, it is hard to diagnose from outside.

**Fix (done):** the limit is set from a measurement, not an estimate. Loading both pinned models
and running one inference of each inside a `python:3.11-slim` container with the CPU torch wheel —
the same shape as `docker/api.Dockerfile` — gave:

| Stage | Peak RSS |
| --- | --- |
| Interpreter baseline | 8 MB |
| After the sentiment pipeline | 599 MB |
| After the summariser pipeline | 1 041 MB |
| After a real inference of each | 1 132 MB |
| **Measured peak** | **1 204 MB** |

`docker-compose.yml` therefore sets `deploy.resources.limits.memory: 2g` on the `api` service —
roughly 66 % headroom over the measured peak, because exceeding a limit is a kill and a summary in
flight allocates transients on top of the resident weights. It is overridable per host with
`API_MEMORY_LIMIT` rather than hard-coded. The same measurement is the input to the scale-out
question in **N5**: ~1.2 GB per process is what makes N replicas expensive.

**Remaining:** the figure above is one model set, one input size and one host. A much longer
transcript, a different torch build, or a host with different allocator behaviour shifts it —
re-measure with `docker stats` after a real deploy and adjust `API_MEMORY_LIMIT` to suit.

### N5 — Every process-local assumption breaks at two replicas ✅ fixed (by decision)
**Where:** `chat_backend/ai_utils.py` (`_PIPELINES` is a module dict),
`chat_backend/ratelimit.py` (documented as per-process, multiplies by N), `chat_backend/realtime.py`
(per-process connection registry), `chat_backend/scaling.py` (the startup guard)
**Impact:** Medium now, and it is a *silent* failure rather than a loud one. Three separate things
are per-process: the loaded models (N replicas → N copies of the weights in memory), the rate-limit
budgets (N workers → every limit is effectively N times looser), and the WebSocket fan-out registry
(a client connected to replica A never sees a message written through replica B — each user just
sees a partial conversation, with no error anywhere).

**Fix (done):** decided, not deferred — the app is **pinned to one process** and the pin is enforced
loudly, with the full note in [`scaling.md`](scaling.md). Three parts:
1. `--workers 1` is now explicit in the image `CMD` rather than implied by the default.
2. `scaling.py` reads the worker count at boot (`WEB_CONCURRENCY`, `UVICORN_WORKERS`, `WORKERS`, a
   `--workers=N` token in `GUNICORN_CMD_ARGS`) and logs it — an `ERROR` naming all three consequences
   and the two ways out if it is above 1, an info line if it is 1. It **warns rather than refuses**,
   on purpose: a platform that forces N workers and cannot be configured should still serve, degraded
   and loudly, rather than crash-loop into a hard outage.
3. Short comments at the three sites that bite, each pointing at `scaling.md`.

**Known limit, stated rather than glossed:** the guard reads what the *process* is told, so
Kubernetes `replicas: 3` with one process per pod is invisible to every pod. That case is covered by
configuration, not by the guard — `replicas: 1` **plus** `strategy: Recreate` or `maxSurge: 0`,
because a default `RollingUpdate` briefly runs two pods and the bug is live for exactly that window.

**Remaining (P17, deliberately not started):** scale-out needs a shared store — Redis pub/sub for
fan-out plus a shared rate-limit store, or Postgres `LISTEN`/`NOTIFY` for fan-out. The model weights
are a separate question: at ~1.2 GB per process the real answer past one replica is a warm model
server the API calls out to, not more copies of the weights.


### N6 — `AI_INFERENCE_URL` was documented but did not exist ✅ fixed
**Where:** `README.md` environment-variable table (row deleted) — there was never a matching field
in `chat_backend/config.py`, and nothing read one
**Impact:** Low at runtime, medium as documentation debt, and it misrepresented the packaging
decision as settled plumbing. The README told an operator there was a setting for pointing
inference at a separate service; setting it had no effect, because `Settings` does not declare it
and no code path consults it. `Settings` uses `extra="ignore"`, so the variable was silently
dropped rather than rejected — the worst failure mode, because the deploy looked successful.
**Fix (done):** the row is deleted rather than annotated, which was the deliberate choice between
the two options. An operator reading a table of *working* settings should not have to check a
caveat column to learn that one of them does nothing, and a variable that is accepted and ignored
is worse than one that is absent. The open question it stood for — whether inference moves to its
own service — is a real question, recorded where it belongs: in the deployment section below and
in [N5](#n5--every-process-local-assumption-breaks-at-two-replicas--fixed-by-decision), not as a
fake env var.

---

## How the NLP layer runs in a deployment

The shape today, and what the items above move toward. Everything in the **N** section exists to
make the left column survivable without changing how the models are called.

**What runs where, right now.** `docker-compose.yml` declares exactly three services — `db`,
`api`, `web` — and there is no `inference` service. `docker/api.Dockerfile` installs the CPU
`torch` wheel and starts Uvicorn; the weights are *not* baked into the image. Inference therefore
runs **inside the API process**:

```
browser ──► web (nginx :8080) ──┬──► api (uvicorn) ──► db (postgres:16)
                                │        └── models resident in this process
                                └──► api (/ws/chat)
```

**Model lifecycle.** Importing `ai_utils` loads nothing — deliberate, so a failed download can
never stop the API from booting (A6). The first request needing a capability calls
`_load_pipeline`, behind a `threading.Lock` with manual double-checked caching so two concurrent
first requests cannot both download it. The result lands in a module-level `_PIPELINES` dict:
**per process, never shared, never persisted** (N5). Both models are pinned to exact 40-char
upstream revisions (`config.py`), so an upstream update cannot silently change stored scores, and
`sentiment_model_info()` writes that provenance beside every stored row.

**The three call paths behave very differently:**

| Path | Threading | If the model fails |
| --- | --- | --- |
| Write-time sentiment (`crud._attach_sentiment`) | `asyncio.to_thread` — non-blocking | message is stored anyway; only the score is lost |
| `POST /analytics/sentiment` | sync `def` route → threadpool | `503` with the reason |
| `GET /analytics/daily` | **blocking call inside `async def`** (N1) | `503` |

**Reads never run inference.** The timeline is a pure SQL aggregate over `message_sentiment`, and
`tests/test_sentiment_persistence.py` fails if a read ever calls the model. The daily summary is
the only user-triggered path that runs a model on demand — which is exactly why N1 matters
disproportionately to how the app feels under load.

**What a deploy actually costs, step by step.** Boot → migrations → warm-up loads both models
(N2, from a volume so the weights download once, N3) → Uvicorn accepting traffic with ~1.2 GB
resident and bounded by the `api` limit (N4) → requests are served without any model download on
the critical path. A second replica duplicates all of that memory and silently splits fan-out and
rate limits (N5).

**Recommended order — this is now done.** N1 and N3 were the cheapest and highest-value (a
one-line code fix and two lines of Compose) and shipped first; N2 and N4 follow and are also in.
What is left, N5, is a decision to record rather than code. N6 went the other way: rather than
build a client for a service that does not exist yet, the variable that did nothing was deleted.

**On the open packaging question.** Splitting inference into its own service buys isolation and
independent scaling, at the cost of a network hop and a second deployable. It should stay closed
until memory or latency actually forces it, and a separate service is the right answer at a scale
where one process cannot hold the weights — not before.

---

## O — Ops, deployment & repo hygiene

### O1 — The Render start command could not resolve the app (closed as obsolete)

**Where:** former `render.yaml` (line 7) — file has been **removed** (decided — Q32/Q41).

**Impact:** Historic. The blueprint as written could not boot: there is no `main.py` at the
repository root (`main.py` lives in `chat_backend/`), so `uvicorn main:app` failed
immediately. Kept here so the failure mode is recorded, not because there is anything left
to fix in a PaaS file.

**Fix:** none — do not re-add a PaaS blueprint. The deployment unit is Docker Compose (gap
**O13**): the `api` container runs `uvicorn chat_backend.main:app` from the repository root
with `PYTHONPATH` at the root.

### O2 — The deployed dependency list was incomplete (closed as obsolete)

**Where:** former `render.yaml` (line 6) + root `requirements.txt` — blueprint removed
(decided — Q32/Q41).

**Impact:** Historic. `pip install -r requirements.txt` installed only `fastapi`, `passlib`,
`pydantic`, `python-dotenv`, `python_jose` and `SQLAlchemy`. Missing: **`uvicorn`** (no
server), **`psycopg2-binary`** (the Postgres driver), **`python-multipart`** (required by
`OAuth2PasswordRequestForm`, so login would 500), plus `transformers`/`torch` for analytics and
`alembic` for migrations.

**Fix:** none in a PaaS file — superseded by the single pinned dependency list plus
`pyproject.toml` (gap **D8**) installed inside the container images (gap **O13**).

### O3 — Migrations never run outside the developer's machine ✅ fixed
**Where:** `docker-compose.yml`, `docker/api.Dockerfile`
**Impact:** Was medium-high: application startup used to create schema implicitly, so Alembic
  history was ignored and drift was invisible.
**Fix (done):** the API container runs `alembic upgrade head` before Uvicorn starts, and
  `create_all()` is removed. The same migration command can be used by a future host's release
  step.

### O4 — No shippable frontend build step ✅ fixed
**Where:** `docker/web.Dockerfile`, `docker/nginx.conf`, `docker-compose.yml`
**Impact:** Was medium. The production image now builds the SPA and serves it from nginx.
**Fix (done):** the `web` service runs a multi-stage frontend build and serves `dist/` on
port 8080 while proxying API and WebSocket traffic to `api`.

### O5 — No health check, no structured logging, no error tracking ✅ fixed
**Where:** `chat_backend/main.py`, `chat_backend/observability.py`
**Impact:** Was medium. `/health` and `/health/ready` now provide safe liveness/readiness
probes, but structured request logging and external error tracking were still absent.
**Fix (done):** health probes plus JSON-lines request logging with correlation:
`chat_backend/observability.py` provides a stdlib `JsonFormatter`, an idempotent
`setup_logging()`, and a middleware that stamps every request with an
`X-Request-ID` (honoured from the client only when header-safe, generated
otherwise), echoes it in the response, and attaches it to the access line and to
the 500 body and traceback line. Health probes log at DEBUG so probes do not
drown real traffic; covered by `tests/test_observability.py`. External error
tracking (Sentry/OpenTelemetry) is deliberately deferred until the app has a
deployment target (U7) — the request id is the correlation key until then.

### O6 — No CI pipeline ✅ fixed
**Where:** `.github/workflows/ci.yml`
**Impact:** Was medium. Pull requests and pushes now run backend lint, migrations, pytest,
frontend lint, frontend Vitest and the production build.
**Fix (done):** GitHub Actions uses a PostgreSQL 16 service for the backend job and Node 22
for the frontend job.

### O7 — No license (closed: not a gap for this project)
**Where:** repository root
**Impact:** None as things stand — this is a solo portfolio repository, and the README states
all rights reserved. Reopen only if external contributions or reuse become a goal, in which
case add `LICENSE` (MIT is the simplest permissive choice) and reference it from the README.

### O8 — No container or local-infrastructure setup ✅ fixed
**Where:** `docker-compose.yml`, `docker/`
**Impact:** Was medium for onboarding: contributors otherwise needed a separately configured
  hosted database and environment.
**Fix (done):** Docker Compose provides PostgreSQL 16, the API, and the nginx-served SPA; the
  documented one-command path is `docker compose up --build`.

### O9 — Rotating the JWT secret on every deploy (closed as obsolete)

**Where:** former `render.yaml` (lines 12–13) — file has been **removed** (decided —
Q32/Q41).

**Impact:** Historic. The old blueprint generated a fresh `SECRET_KEY` per deploy, silently
invalidating every issued token; the sharing-across-services problem is now answered by
injecting one value into every container from the same secret store at deploy time.

**Fix:** none in a PaaS file. Secrets travel with the deployment environment (Compose env
file / host secret store); the minimum bar is failing fast when `SECRET_KEY` is missing
(gap **S5**).

### O10 — Documentation was stale (addressed)
**Where:** `README.md`, `chat_frontend/README.md`
**Impact:** Medium — a reader could not get the project running: the README pointed at
`uvicorn app.main:app`, which is not the module path, used `py -m pip install -r
requirements.txt` while the complete list is now the root `requirements.txt`, and it
described only the backend. The frontend README was the untouched Vite template.
**Fix:** done in this change — the root README documents both halves, the correct commands,
the environment variables, the API and the known gaps, and the frontend README now describes
the actual source layout. `.env.example` was added since `.env` is git-ignored.

### O11 — Local secrets and tooling artifacts
**Where:** `.env` (untracked), `.qodo/` (empty scaffolding folders)
**Impact:** Low-medium. `.env` is correctly ignored, but the Supabase password in it has been
on disk in plaintext and should be rotated (S5). `.qodo/` contains only empty
`agents`/`workflows` directories — harmless but unexplained.
**Fix:** rotate the credential, keep only placeholders in `.env`, verify with
`git check-ignore -v .env`, and either populate or remove `.qodo/`.

### O12 — No dependency or security scanning ✅ fixed
**Where:** `.github/dependabot.yml`, `.github/workflows/ci.yml`, `chat_frontend/package.json`
**Impact:** Low-medium. `package-lock.json` is committed, Python dependencies are partly
unpinned (D8), and nothing audited for known CVEs.
**Fix (done):** Dependabot watches `pip`, `npm` (in `chat_frontend/`) and `github-actions`,
weekly and grouped so an update arrives as one reviewable PR. CI audits both halves:
`npm audit --omit=dev --audit-level=high` gates the frontend and is currently clean —
`@tailwindcss/vite` moved to `devDependencies`, where a build-time tool belongs, which took the
Vite dev-server advisories out of the production tree, and `npm audit fix` bumped
`react-router` inside its existing range. The backend half was then cleared in this pass:
`fastapi 0.116.1 → 0.142.0` admits `starlette >= 0.46.0` with no upper bound, so `starlette` moved
to `1.7.0` and its six advisories with it; `python-multipart 0.0.6 → 0.0.32` clears nine
(including the ReDoS); `python-dotenv 1.1.1 → 1.2.3`; `anyio (>=4,<5)` and `httpx2` arrived with
starlette 1.x for the TestClient. `pip-audit` now reports exactly one package with advisories:
`transformers 4.53.0` — 12 advisories, 9 of which have no fixed release at all and 3 of which are
fixed only in the 5.x line, a major bump the A7 evaluation run would have to re-validate the pinned
models against. The CI step therefore still runs with `continue-on-error`, and its comment now
states precisely what remains and why.
**Remaining:** the `transformers` 4→5 upgrade (then drop `continue-on-error`); 9 of its advisories
have no fixed release upstream, so the step cannot gate before then.

### O13 — No containers: no Compose stack, no Dockerfiles ✅ fixed
**Where:** `docker-compose.yml`, `docker/`
**Impact:** Was high for "shippable". The repository now has a reproducible three-service path.
**Fix (done):** `docker compose up --build` starts PostgreSQL 16, runs Alembic in the API
container and serves the SPA/API/WebSocket through nginx at `http://localhost:8080`.

---

## T — Testing & developer experience

### T1 — The backend has no tests ✅ fixed
**Where:** `tests/`
**Impact:** Was high for confidence: bugs like B2 stayed unnoticed with no suite.
**Fix (done):** 137 tests collected (135 pass, 2 skipped) via `pytest` +
`pytest-asyncio` + `httpx.ASGITransport` against a real PostgreSQL 16 container: register/login/duplicate/wrong-password, `GET /users/me`
(with and without token), message create/list/ownership/delete/input-limit, bounded keyset
pagination, analytics with monkeypatched models (no download), daily-summary user scoping,
WebSocket accept/reject/first-frame-auth/persistence/fan-out, account deletion with the
ON DELETE CASCADE check, security headers (strict vs Swagger CSP), and the
structured-logging layer (JSON formatter, request-id echo, access-log
correlation). Per-test isolation via
`TRUNCATE … RESTART IDENTITY`.

### T2 — The frontend has no tests ✅ fixed
**Where:** `chat_frontend/src/**/*.test.ts(x)`
**Impact:** Was medium. The frontend now has a regression suite for the auth boundary, the `fetch`
client and the query layer.
**Fix (done):** Vitest, React Testing Library and jsdom cover anonymous redirects, valid-token
access, expiry-driven logout, message de-duplication, owner-only deletion, the `fetch` client
(token header, query mapping, `ApiError`, 401 handler), the TanStack Query retry policy, the
composer and delete mutations, the keyset "load older" cursor, the daily-summary query, plus the
realtime layer — `useChatSocket` (heartbeat timeout, reconnect backoff, auth rejection, HTTP
fallback) and `parseFrame` protocol tests — plus the MSW harness (T5): page-level Chat tests
that run the real `apiClient`/query stack against `src/test/handlers.ts`, and the index.html
CSP baseline — 90 tests across 13 files. **Auth forms added:**
`src/test/authForms.test.tsx` drives the real login and register forms through the
real `apiClient` against MSW, covering the form-encoded login body (a JSON body
there would answer `422` and the user would be told to "provide both fields" for
no reason), navigation on success, the `401` and taken-username error copy, the
retained password field, and the disabled empty-form state. That last gap is why
`mswState` records request bodies rather than only answering them.

### T3 — No static analysis for Python ✅ fixed
**Where:** `pyproject.toml`
**Impact:** Was medium: unused imports and type errors went unflagged.
**Fix (done):** `ruff` (E4/E7/E9/F/I, py311 target) and `mypy` (non-strict
baseline: `check_untyped_defs`, `ignore_missing_imports`, plus the `pydantic.mypy`
and `sqlalchemy.ext.mypy.plugin` plugins) are both configured in `pyproject.toml`,
both pass clean over `chat_backend`, `tests`, `alembic`, and both run in CI (O6).
`mypy` drove two real fixes: `Mapped[]` annotations on the models (so `user.id`
checks as `int` instead of `Column[int]`) and an honest `JSONResponse` return
type on `/health/ready`. Pinned as `mypy==2.3.1` in `requirements.txt`.

### T4 — No `pyproject.toml` / project metadata ✅ fixed
**Where:** `pyproject.toml`
**Impact:** Was low-medium: no home for tool config or project metadata.
**Fix (done):** `pyproject.toml` added with `[project]` metadata plus
`[tool.pytest.ini_options]` and `[tool.ruff]` sections; dependency pins stay in the single
`requirements.txt` (Q15).

### T5 — No shared test harness ✅ fixed
**Where:** `tests/conftest.py`, `chat_frontend/src/test/`
**Impact:** Was medium-high as a blocker for T1/T2.
**Fix (done):** backend fixtures (async HTTP client, PostgreSQL isolation with a
schema rebuilt from the models each session, `NullPool` socket client); frontend
Vitest environment with jsdom, Testing Library and a `QueryClient` render
helper. **MSW added:** `src/test/handlers.ts` mirrors the REST surface
(keyset pagination, bearer header recording), and `Chat.msw.test.tsx` drives the
page through the real `apiClient` + TanStack Query stack end to end — fetch,
query-string mapping, cache updates and the HTTP send path — instead of
`vi.mock`-ing the api module. The `fetch` client keeps its own stubbed-fetch
unit tests.

---

## P — Product features (not defects)

These are the gaps between "a working demo" and "a chat app someone would return to".

| ID | Feature | Why it matters | Rough effort |
| --- | --- | --- | --- |
| P1 | **Conversations/rooms or DMs.** Today every message lands in one global timeline; there is no `conversation` table, no membership model and no way to talk to a specific person. This is the largest structural gap. | A chat app without conversations is a guestbook. | L |
| P2 | **Typing indicators and presence.** The socket is a natural transport once B1 is done — `{type: "typing"}` frames plus a broadcast of online user ids. | Makes the realtime layer feel alive. | M |
| P3 | **Read receipts / unread counts.** Requires a `message_reads` table or a `last_read_at` per user per conversation. | Users cannot tell if anyone saw their message. | M |
| P4 | **Message search.** Postgres full-text search (`tsvector` + GIN index) over `messages.text`, or `pg_trgm` for fuzzy search. | The main reason people scroll back through old chats. | M |
| P5 | **Edit messages.** Delete from the feed is complete; editing needs `updated_at` and an update endpoint (D5). | Basic message hygiene. | S–M |
| P6 | **Pagination / infinite scroll and history.** The API and a manual load-older control are complete; automatic infinite scroll and broader conversation history remain. | Older conversations should be easy to browse. | S |
| P7 | **Attachments and images.** Needs object storage (Supabase Storage or S3), upload endpoints, type/size validation and a preview UI. | Text-only chat feels dated. | L |
| P8 | **User profiles and avatars.** Display names instead of "User 3" (F10), plus an avatar upload. | Identity is core to chat. | M |
| P9 | **Password reset and email verification.** Requires an email provider and token flow. | Locked-out users currently have no recovery path. | M |
| P10 | **Social login (Google/GitHub OAuth).** | Removes registration friction. | M |
| P11 | **Notifications** (browser push or email digest for mentions/unread). | Brings users back. | M–L |
| P12 | ~~**Analytics dashboard with charts.**~~ **Partly done:** the sentiment trend chart shipped (window selector, SVG bars, data table). Left: message-volume as its own chart, most active hours, keyword cloud. | Turns the AI features into something visual — the Analytics page used to be two buttons. | S for the rest |
| P13 | **Export / transcript download.** `GET /conversations/{id}/export?format=md|json|csv`, plus a shareable link for the daily summary. | Easy win, high perceived value. | S |
| P14 | **Admin/moderation tools.** No way to remove abusive content or ban a user; today deletion is self-service only. | Required before any public launch. | M |
| P15 | **Localisation and dark mode.** Tailwind makes a theme toggle cheap; `Intl` handles dates. | Polish that users notice. | S–M |
| P16 | **All-users ("global") broadcast.** M2 fans messages out per user, because a client may only be pushed messages it is allowed to read back (S2). Pushing *every* message to *every* connected client is a separate product decision, and it only becomes coherent once the feed itself stops being author-scoped (P1/U1). | The cheapest way to make realtime visible across two accounts; deliberately a future feature, not an M2 default. | M |
| P17 | **Shared state for scale-out — Redis.** The single-process pin (N5, [`scaling.md`](scaling.md)) is the ceiling, not a strategy. Lifting it means a shared store: Redis pub/sub for WebSocket fan-out (replacing the per-process registry) and a shared counter store for the rate limiter, or Postgres `LISTEN`/`NOTIFY` for fan-out alone. Model weights are a separate question — past one replica the right answer is a warm model server, not N copies at ~1.2 GB each. | The prerequisite for running more than one instance. Buy it when vertical scaling runs out, not before: it is real infrastructure to run and to keep running. | L |

---

## Milestone sequencing

- **M1 — shippable core.** Migrations decided and applied; a clean clone runs and is worth trusting. ✅ done — two items left: D11, O11.

- **M2 — realtime + safety.** The WebSocket became a real channel with per-user fan-out, plus the auth and robustness work (CSP, cascading account deletion, connection pooling, MSW page tests). ✅ done.

- **M3 — AI done right + polish.** Persisted sentiment, distilled and lazily loaded models, the finished UI, registration policy and per-IP rate limits. ✅ done — S9 moved to M4 by decision.

- **M4 — cookies + refresh.** Refresh-token rotation with server-side logout on the single-origin cookie setup. ✅ done.

- **M4b — NLP in production.** Warmup at boot, the model cache on a volume, a memory limit set from a measured 1 204 MB peak, and the single-process pin ([`scaling.md`](scaling.md)). ✅ done — N1–N6.

- **Later — product.** P1–P17, starting with the trends dashboard (A3, A4, D7).

