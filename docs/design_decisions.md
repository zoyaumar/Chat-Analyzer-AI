# Design decisions

Why each technology is in this codebase, whether it was the right call, and what the alternative
would have been.

Every entry follows the same shape:

- **Decision** — what is actually in the code today.
- **Why** — the reasoning that justified it.
- **Trade-offs** — what it costs, honestly.
- **Alternatives** — what else was on the table.
- **Verdict** — keep it, change it, or "revisit when…".

> **Status tags:** ✅ keep · 🔄 revisit · ⚠️ should change soon · 🔒 deliberately deferred.

---

## Contents

- [1. Backend framework & data access](#1-backend-framework--data-access)
- [2. Authentication & security](#2-authentication--security)
- [3. Database, schema & migrations](#3-database-schema--migrations)
- [4. Real-time transport](#4-real-time-transport)
- [5. AI / NLP](#5-ai--nlp)
- [6. Frontend](#6-frontend)
- [7. Deployment & operations](#7-deployment--operations)
- [8. Project structure & conventions](#8-project-structure--conventions)
- [9. Undecided / open questions](#9-undecided--open-questions)
- [10. Post-review decisions](#10-post-review-decisions)
- [Review dissents — outcomes](#review-dissents--outcomes)
- [Decision log](#decision-log)

---

## 1. Backend framework & data access

### Q1. Why am I using FastAPI instead of Flask, Django, or Express?

**Decision.** FastAPI, with routers split per resource (`chat_backend/routes/*.py`).

**Why.**
- Native WebSocket support in the same process — a chat app needs both REST and a socket, and
  FastAPI gives both without adding a second service or a Socket.IO-style wrapper.
- Pydantic v2 request/response models double as the OpenAPI schema, so `/docs` is always a
  truthful description of the API rather than documentation that drifts.
- Dependency injection (`Depends(get_db)`, `Depends(get_current_user)`) makes the "current
  user + database session" pattern reusable per route with one line.
- Python keeps the backend and the NLP models in one language and one deployable unit.

**Trade-offs.** Less batteries-included than Django: no admin panel, no built-in
permissions/groups, no ORM-level migrations of its own (hence Alembic), and the async
ecosystem requires deliberate choices (sync vs async DB driver, blocking model inference).

**Alternatives.** Django + Django REST Framework would give an admin UI and a mature auth
stack out of the box, but Channels adds complexity for WebSockets and the NLP stack would
still be separate. Flask would mean assembling validation, async and WebSocket support by
hand. Node/Express would split the codebase across two languages for no benefit here.

**Verdict.** ✅ Keep. For "REST + WebSocket + a Python ML library", FastAPI is the shortest
path that stays typed and documented.

### Q2. Should I use async SQLAlchemy instead of the sync `Session`?

**Decision.** Async SQLAlchemy end-to-end: `create_async_engine` + `asyncpg`, an `AsyncSession`
from `async_sessionmaker`, an async `get_db` dependency and `async def` route handlers.
*(Changed after review — completed in M1; the backend now uses `AsyncSession`.)*

**Why.**
- The WebSocket handler is `async` and must write messages (Q42). With a sync session it either
  blocks the event loop or needs `run_in_threadpool` scattered around, and one concurrency model is
  much easier to reason about than two.
- The conversation-heavy endpoints are I/O-bound; `asyncpg` serves more concurrent requests with
  fewer resources than a psycopg2 threadpool, which matters once the socket and REST calls share a
  single process.
- FastAPI's dependency system is async-native, so `Depends(get_db)` yielding an `AsyncSession` is
  the well-trodden path rather than a workaround.

**Trade-offs.**
- Every handler changes from `def` to `async def` and every query is `await`ed — a codebase-wide
  change, which is precisely why it should happen now (M1) rather than after the socket exists.
- Blocking work must not run on the event loop: the NLP pipeline and password hashing have to move
  to a threadpool (`anyio.to_thread.run_sync`) or out of the process (M3).
- Alembic runs outside the app: keep a sync URL (`DATABASE_URL_SYNC`) or use
  `connection.run_sync(context.run_migrations)`. Two drivers is the one sharp edge; the settings
  object makes both URLs explicit so nobody has to guess.

**Alternatives.** Keep the sync session and wrap socket DB calls in `run_in_threadpool` (the
pre-M1 alternative); the `databases` library; **psycopg3**, which is worth noting because one driver
covers both sync and async usage, halving the configuration surface.

**Verdict.** ✅ **Done in M1.** The backend uses `AsyncSession` end-to-end, with the async migration
environment and route handlers in place. Gap **B13** is closed; the remaining sharp edge is
running blocking password/NLP work off the event loop.

### Q3. Should I move to Django so I get auth and an admin panel for free?

**Decision.** No — stay on FastAPI.

**Why.** The custom parts of this app (JWT issuance, arbitrary per-user message queries, model
inference endpoints) are exactly the parts Django would not hand over, while the parts Django
would help with (admin, sessions) are not currently needed.

**Trade-offs.** Features that would be free in Django must be written here: password reset,
email verification, permissions, moderation tooling (gaps P9, P14).

**Verdict.** 🔒 Deferred. If moderation or back-office tooling becomes a requirement, the
cheapest path is `sqladmin`/`fastapi-admin` bolted onto the existing models rather than a
framework migration.

---

## 2. Authentication & security

### Q4. Why am I using JWT instead of server-side sessions?

**Decision.** Stateless JWTs signed with `HS256`, carrying `{"sub": "<user_id>", "exp": …}`
(`chat_backend/auth_utils.py`), returned from `POST /users/login` as a bearer token.

**Why.**
- No session store to run (no Redis, no sticky sessions), which matters on a free tier.
- Sending a bearer token in an `Authorization` header fits the REST + WebSocket model: the same
  token can be validated once at socket handshake, without a second auth round-trip.
- The token is self-contained, so the API needs no lookup to know *who* is calling.

**Trade-offs.**
- **Revocation is the hard part.** Anything signed stays valid until `exp`; there is no logout
  server-side today (gap S7).
- The client now schedules renewal from the JWT `exp` claim and handles server 401s, so an
  expiry is visible rather than silent. Revocation is server-side through the rotating
  refresh token (gap S7, done — Q9).
- Because the payload is readable, anything put in it is public — do not add PII or roles
  without understanding that.

**Alternatives.** Server sessions with an `HttpOnly` cookie and a `sessions` table (simple
revocation, needs shared state); `fastapi-users` for a managed implementation of the whole
flow; opaque tokens in a database with a cache in front.

**Verdict.** ✅ Keep JWT, but fix the two things that make it *look* broken: the `exp` value
comes from configuration (gap B6), and the client now handles expiry and 401s (F4/F5).
`iat` + `jti` ship with the payload (gap S7 done), and the revocable half of the session is
the rotating refresh token (Q9).

### Q5. Should I store the token in `localStorage`, a cookie, or in memory?

**Decision.** In memory, plus an `HttpOnly` refresh cookie. The access token is a
module-level variable (`src/auth/token.ts`) attached by the API client wrapper
(`setUnauthorizedHandler`/`setSessionRefresher` + the bearer header in `src/apiClient.ts`,
Q27); the durable half of the session is a rotating refresh token in an
`HttpOnly; SameSite=Strict; Path=/users` cookie (Q9). *(Revisited in M4 — the legacy
`localStorage` copy is adopted once on boot, then deleted.)*

**Why.** In-memory is XSS-resistant: there is nothing on disk for an injected script to
read. The cookie carries durability across reloads without ever entering JavaScript's
reach — `HttpOnly` is the line XSS does not get to cross. Same-origin serving (Q34) is what
makes the cookie viable: no cross-origin credentials problem, and `SameSite=Strict` keeps it
off every cross-site request.

**Trade-offs.** The access token dies on reload, so a single-flight boot refresh restores
the session — and `RequireAuth` waits for `initialised` instead of flashing the login page
while it runs. The cookie brings a CSRF surface, answered by `SameSite=Strict` plus the
explicit `Sec-Fetch-Site`/`Origin` guard on login/refresh/logout (Q9). `Secure` is a switch
(`REFRESH_COOKIE_SECURE`) because a browser drops a Secure cookie over plain HTTP.

**Alternatives.**
| Option | Security | Cost |
| --- | --- | --- |
| `localStorage` (the original decision) | XSS-readable | none |
| In-memory only | XSS-resistant, lost on refresh | needs silent refresh or re-login |
| `HttpOnly` cookie only | XSS-resistant, sent automatically | needs CSRF protection; XSS can trigger actions but cannot read |
| Cookie + in-memory access token (today) | strongest practical | most moving parts (refresh endpoint, rotation) |

**Verdict.** ✅ **Done (M4)** — chosen option above, gaps **S9** and **S7** closed. S8
(first-frame WebSocket token) landed earlier as its own fix, and single-origin (Q34) is what
made the cookie option realistic.

### Q6. Why am I using bcrypt, and should I switch to Argon2?

**Decision.** `pwdlib` with two hashers: `Argon2Hasher` writes every password registered from now
on, and `BcryptHasher` is kept only so hashes written before the migration still verify
(`chat_backend/auth_utils.py`).

**Why.** bcrypt is a well-understood, widely deployed password hash and `passlib` was the
conventional way to reach it from Python — that was the original decision here. Both halves aged
badly: bcrypt truncates input beyond 72 bytes (silently), OWASP's first recommendation is
Argon2id, and `passlib` is effectively unmaintained (1.7.4, 2020).

**Trade-offs.** The database carries two hash formats until accounts rehash themselves (cheap, and
self-limiting), and argon2's defaults are deliberately slower per login than bcrypt's. The 72-byte
registration cap stays even though argon2 would accept more: a password only the legacy hasher can
verify is a password the system can no longer check.

**Alternatives.** Direct `argon2-cffi` (what `pwdlib` wraps, without the rehash helper), direct
`bcrypt`, or standard-library `hashlib.scrypt`.

**Verdict.** ✅ done (S10). `PasswordHash((Argon2Hasher(), BcryptHasher()))` hashes with the first
hasher and verifies with whichever one matches the stored format; `verify_and_rehash()` returns a
replacement when one exists and `POST /users/login` persists it, so an account moves to argon2id on
the login that proves it — no lockout and no backfill script. `tests/test_auth.py` proves a
pre-migration bcrypt hash still logs in and is rewritten to `$argon2id$`.

### Q7. Should I keep `passlib`?

**Decision.** No — `passlib` is removed (gap S10).

**Why.** It was one line (`pwd_context.hash/verify`) and switching hashers without a migration plan
risks locking users out, so the plan was always: keep it, pin `bcrypt`, migrate with tests.

**Trade-offs.** An unmaintained dependency sits on the critical auth path with no upper bound on
`bcrypt` — a future release can break hashing silently — and the pin that prevented that
(`bcrypt<4.1`) also held the app back from bcrypt's own fixes.

**Verdict.** ✅ done: `passlib` is out of `requirements.txt`, `pwdlib[argon2,bcrypt]` with
`bcrypt 5.0.0` and `argon2-cffi 25.1.0` are pinned instead, and the tests this verdict asked for —
old hashes proving they still verify — are in `tests/test_auth.py`. The stopgap retires with it.

### Q8. Why `python-jose` and not `PyJWT`?

**Decision.** **PyJWT**, replacing `python-jose`. *(Completed in M1; the backend now imports `jwt`.)*

**Why.**
- Only two calls are used (`jwt.encode`, `jwt.decode`), so the broader JOSE/JWE surface of
  `python-jose` is unused weight sitting on the authentication path.
- `PyJWT` is the more widely used and more actively maintained of the two, which is exactly the
  property you want in the component that decides whether a token is trustworthy.
- The migration is mechanical: `jwt.encode(payload, key, algorithm="HS256")`,
  `jwt.decode(token, key, algorithms=["HS256"])`, and `jwt.exceptions.InvalidTokenError` in place
  of `JWTError`. Note that `algorithms=[...]` must stay explicit — that is the check that prevents
  algorithm-confusion attacks.

**Trade-offs.**
- Touching auth code always carries risk, which is why it lands together with the first pytest
  coverage of login and the protected routes (M1) instead of on its own.
- `python-jose` supports more of the JOSE specification; if JWE or nested tokens ever become a
  requirement, this decision is worth revisiting.

**Alternatives.** Kept `python-jose` (3.5.0) until the swap; `authlib` if third-party OAuth
providers (gap P10) are added, since it covers the client side of that flow too.

**Verdict.** ✅ **Done** — the code now uses `PyJWT` (gap **B14** closed), and `iat`/`jti`
ship in the payload so the refresh flow got a format it can build on (Q9/S7 done).

### Q9. Should I add refresh tokens and a logout endpoint?

**Decision.** Yes — a rotating refresh token stored SHA-256-hashed in a `refresh_tokens`
table, carried in an `HttpOnly` cookie, with `POST /users/logout` revoking it server-side.
Access tokens stay short-lived (30 minutes by default) and stateless. *(Completed in M4.)*

**Why.** Revocation needs one row the server can delete; keeping the access token cheap and
stateless while the refresh token anchors the session gets both properties. Rotation —
delete + reissue on every `POST /users/refresh` — means each token works exactly once, so a
stolen copy dies the moment either side refreshes.

**Trade-offs.** One table written only on refresh/logout, not per request; two parallel
refreshes would strand each other, which the client answers with a single-flight refresher.
The cookie's CSRF surface is met by `SameSite=Strict` plus the `require_same_origin` guard
(`Sec-Fetch-Site`, then `Origin`) on login, refresh and logout; `Secure` follows
`REFRESH_COOKIE_SECURE` because plain-HTTP local dev would otherwise drop the cookie. The
client distinguishes a failed *boot* refresh (silently "not signed in") from a failed
*mid-session* renewal (an expiry worth the notice).

**Verdict.** ✅ **Done (M4)** — `POST /users/refresh` rotates and purges expired rows,
`POST /users/logout` deletes the session's row, login sets the
`HttpOnly; SameSite=Strict; Path=/users` cookie, and the SPA renews at expiry instead of
bouncing to login. Backend coverage in `tests/test_auth.py`; client coverage in
`AuthContext.test.tsx` (boot refresh, no login flash, rotation-driven renewal) and
`apiClient.test.ts` (401 → refresh → one replay).

---

## 3. Database, schema & migrations

### Q10. Why PostgreSQL, and where should it run?

**Decision.** PostgreSQL 16, running locally as a `db` service in Docker Compose. The previous setup
pointed *development* at a shared hosted instance (Supabase). *(Changed after review: container for
development, managed instance optional for hosting.)*

**Why.**
- Postgres is the right engine for this app: `timestamptz`, real full-text search for message search
  (gap P4), `pg_trgm` for fuzzy matching, `LISTEN/NOTIFY` for cross-instance fan-out (Q18), and
  `pgvector` if the AI features ever need embeddings.
- One engine in development and in production means no dialect surprises — types, timezone
  behaviour, JSON operators and `ILIKE` all behave the same way.
- The container removes the two problems a shared remote development database created: a bad
  migration could hit real data, and the schema people developed against was not reproducible —
  which is how the alter-only Alembic revision (gap D1) went unnoticed.
- A managed instance is still a reasonable *hosting* choice; the change is that it is no longer the
  development environment.

**Trade-offs.** Compose adds a container and a volume to manage. The dev database is disposable and
recreated on demand, which is fine here because seed data belongs in fixtures rather than in a shared
cluster. Hosted Postgres over the network still needs pooler-aware settings (gap D9).

**Alternatives.** Continue with only a hosted instance (rejected: couples dev to prod and to the
network); SQLite for development (rejected: different dialect, and its async story would diverge from
production too); Neon/Railway/Supabase as the hosted target once deployed.

**Verdict.** ✅ Decided — `db: postgres:16` in Compose for development (gap **O13**), managed instance
reserved for deployment.

### Q11. Should I use the Supabase client (`supabase-py`) instead of SQLAlchemy?

**Decision.** SQLAlchemy against the Postgres connection string. The `supabase` client was
listed as a dependency but **never imported anywhere** in the codebase, and has been removed.

**Why.** The app needs arbitrary query composition (filters, ordering, join relationships,
`func.now()` defaults, Alembic-driven DDL), and SQLAlchemy expresses all of that directly.
Supabase's REST/PostgREST layer is optimised for row-level-security-scoped client access, not
for a server that already holds its own credentials.

**Trade-offs.** Two mental models live in one repo: the docs and dependencies imply Supabase
tooling while the code is plain SQLAlchemy + psycopg2. The unused dependency is dead weight and
a supply-chain surface (gap D8).

**Verdict.** ✅ **Done:** the unused `supabase` dependency is absent from the consolidated
requirements list (gap **D8**). Revisit only if Supabase Storage is adopted for attachments (gap
P7) or Supabase Auth replaces the hand-rolled JWT flow — which would absorb Q4 as well.

### Q12. Why the SQLAlchemy ORM instead of raw SQL or SQLModel?

**Decision.** SQLAlchemy 2.0 declarative models (`User`, `Message`) with a `declarative_base`,
plus Alembic autogenerate.

**Why.**
- Relationships (`User.messages` / `Message.user`) come free and are already used by the schemas
  (`MessageWithUser`).
- Alembic autogenerate diffs `Base.metadata`, which removes hand-written DDL from the loop.
- It is the most widely used Python ORM, so examples and answers are abundant.

**Trade-offs.** The ORM hides the SQL, which is exactly why D3 (missing indexes) and D4 (lost
`ON DELETE CASCADE`) are easy to miss. Lazy-loaded relationships can also cause N+1 queries if
`MessageWithUser` is ever returned from a list endpoint.

**Alternatives.** `SQLModel` (Pydantic + SQLAlchemy in one class, which would remove the
duplicate schema/model definitions but couples API shape to table shape); `databases`/raw SQL
with `text()` (fast and explicit, no autogenerate); an async ORM (see Q2).

**Verdict.** ✅ Keep. 🔄 If the schema stops changing, the duplication between `models.py` and
`schemas.py` will start to feel like overhead — that is when SQLModel becomes tempting, not
before.

### Q13. Why do I have both Alembic *and* `create_all()`?

**Decision.** Alembic is the only schema writer. The initial revision creates the `users` and
`messages` tables, and the Compose API runs `alembic upgrade head` before Uvicorn starts.

**Why.** One owner for DDL keeps a fresh database reproducible, makes schema changes reviewable,
and prevents the application and migration history from silently disagreeing.

**Trade-offs.** A new environment must run the migration step; the existing development database
may need a one-time `alembic stamp head` because its tables predate migration tracking.

**Alternatives.** `create_all()` only is fine for a throwaway prototype, but it cannot alter an
existing schema or represent a reviewed migration history.

**Verdict.** ✅ **Done in M1.** The alter-only revision was replaced with a true initial migration,
`create_all()` was removed from application startup, and empty-database upgrades are verified in
CI and the test workflow. Gaps **D1**, **D2**, **B9**, **D11**, **O3**.

### Q14. Why integer primary keys instead of UUIDs or ULIDs?

**Decision.** `Integer` auto-increment primary keys on both tables (the migration even converts
Supabase's original `BIGINT` columns down to `Integer`).

**Why.** Small, index-friendly and human-debuggable ids — `/messages/12` is easy to reason about
in logs and curl commands.

**Trade-offs.** Sequential ids are guessable (they leak volume and enable enumeration — relevant
if message access ever became id-based instead of ownership-filtered), and merging data across
environments or importing from another system collides.

**Alternatives.** `UUID` (`uuid4` or `gen_random_uuid()`) for distribution safety, at the cost of
larger indexes; time-sortable ids (`ULID`, `uuid7`, or a Snowflake-style `BigInteger`) for keyset
pagination without an extra column.

**Verdict.** ✅ Keep integers for now (every read is accompanied by an ownership check), 🔄
revisit if the API is exposed publicly, message permalinks are shared, or multi-region writes
become a requirement.

### Q15. Why are there two `requirements.txt` files, and should I use `uv` or Poetry?

**Decision.** Collapse to **one pinned runtime list** plus a `pyproject.toml` for metadata and tool
config, and adopt `uv` when convenient. **Done** — there is now a single pinned root
`requirements.txt`; `chat_backend/requirements.txt` was deleted.

**Why.**
- Two files with different contents is a bug factory: the root one cannot boot the app (no
  `uvicorn`, no `psycopg2-binary`, no `python-multipart`) while the backend one is unpinned and
  therefore not reproducible.
- The M1 work changes the dependency set anyway — `sqlalchemy[asyncio]`, `asyncpg`, `PyJWT`,
  `pydantic-settings`, `pytest`, `ruff` — so this is the natural moment to establish one source of
  truth.
- `pyproject.toml` gives `ruff`, `mypy` and `pytest` a single home and removes the "where does this
  config live?" question (gap T4).
- With no platform-specific build config in the repo (Q32), a plain pinned file keeps any
  container build reproducible without extra tooling.

**Trade-offs.** One list means the API image installs AI dependencies it may not use. If inference
moves into its own service (U4), the two deployables will eventually want separate lists — that is
the point where `uv` dependency groups or a `requirements/` directory earns its keep.

**Alternatives.**

| Tool | Fits when |
| --- | --- |
| One pinned `requirements.txt` | smallest change, works with any container build |
| `requirements.in` + `pip-compile` | want pins without maintaining them by hand |
| `pyproject.toml` + `uv.lock` | want a fast resolver, dev groups and a lockfile in one tool |
| Poetry | want packaging and dependency groups in one manifest |

**Verdict.** ⚠️ **Decided (M1):** one pinned `requirements.txt` for runtime dependencies plus
`pyproject.toml` for metadata and tooling (gaps **D8**, **T3**, **T4**), with the
`torch --index-url` footgun fixed and the unused `supabase` client dropped (gaps **A5**, **Q11**).
Moving to `uv` afterwards is a follow-up, not a blocker.

---

## 4. Real-time transport

### Q16. Why WebSockets instead of polling or Server-Sent Events?

**Decision.** A single WebSocket endpoint (`WS /ws/chat`) alongside the REST API.

**Why.** Chat is bidirectional and server-pushed by nature: the client needs to send without
per-request overhead and the server needs to push without the client asking. Polling would put
artificial latency on message delivery and multiply request volume; SSE is server→client only,
so sending would still need REST.

**Trade-offs.** WebSockets are stateful: the connection must be authenticated at handshake,
kept alive, tracked per process, and re-established after network changes. That state also means
horizontal scaling needs a shared fan-out mechanism (see Q18).

**Alternatives.**

| Option | Verdict for this app |
| --- | --- |
| Short polling (`setInterval` + `GET /messages/`) | simplest, and a legitimate first version — but wasteful and laggy |
| Long polling | middle ground, still awkward to write |
| SSE + REST for writes | good fit if the app only needed notifications; less natural for a two-way chat |
| WebSocket (current) | the right destination for chat, with full lifecycle management |
| Managed realtime (Supabase Realtime, Pusher, Ably) | removes the plumbing, adds a vendor and cost |

**Verdict.** ✅ **Implemented in M2 (gaps S1, S8, B1, F3, F11).** The WebSocket endpoint provides bidirectional, authenticated communication. First-frame authentication validates JWTs without exposing credentials in query parameters. Messages are persisted through `crud.py` and broadcast to active sockets scoped per user. The client (`useChatSocket`) integrates automatic reconnection with backoff, defensive parsing, heartbeat pings/pongs, and transparent fallback to REST when disconnected.

### Q17. Should I use Socket.IO or a managed realtime service instead of hand-rolled WebSockets?

**Decision.** Hand-rolled `ConnectionManager` (now in `chat_backend/realtime.py`).

**Why.** FastAPI's `WebSocket` + a list of connections is enough for one process and keeps the
dependency list small; no extra protocol layer is needed for a plain-text/broadcast chat.

**Trade-offs.** Everything Socket.IO gives for free must be written here: reconnection with
backoff, rooms, acknowledgements, heartbeats, and a fallback transport. A `ConnectionManager`
holding `List[WebSocket]` also breaks the moment more than one worker process runs, because
sockets are tied to a process.

**Alternatives.** `python-socketio` (rooms, reconnection, acks, battle-tested); Supabase Realtime
(Postgres change feeds over WebSocket — genuinely attractive here because the data *is* already in
Supabase); Pusher/Ably (fully managed).

**Verdict.** ✅ Keep the hand-rolled manager — it is the right amount of machinery for one broadcast
target, and implementing it is a large part of why this project exists. 🔄 Revisit once rooms (gap
P1), per-user presence (P2), an all-users broadcast (P16) or more than one worker process are on the
table, where `python-socketio` (or Supabase Realtime) starts paying for itself. M2 is scoped so that
switching later is a transport swap rather than a rewrite: messages are created through the service
layer, and clients receive a plain `Message` JSON document either way. M2's fan-out is per user on
purpose — a client is only pushed messages it is allowed to read back (S2) — so broadcasting to
*every* connected client is recorded as a future feature (gap P16) rather than being the default.

### Q18. Should I broadcast through Redis pub/sub?

**Decision.** No — the current `broadcast` iterates a list in memory. And the
consequence is now **decided rather than implied**: the app is pinned to one process, explicitly
(`--workers 1` in the image `CMD`) and loudly (a startup guard logs the worker count, and an
`ERROR` naming all three failure modes if it is above 1). Full note in [`scaling.md`](scaling.md);
implementation in `chat_backend/scaling.py`; the same pin applies to the rate limiter and the model
cache, not just this module (gap N5).

**Why.** One process, one instance, no Redis to run. Correct for development — and, at this size,
correct in production too. What was missing was not the answer but the *enforcement*: an implicit
single-process assumption is one `WEB_CONCURRENCY` setting away from breaking, and it breaks
silently.

**Trade-offs.** With more than one worker (or a reloader spawning one), clients connected to
instance A never see messages written through instance B. The failure is silent: each user just
sees a partial conversation. The pin removes the ambiguity but does not remove the ceiling — the
single process is the scaling limit, and three things are now known not to be horizontally
scalable: this registry, the rate-limit counters, and the resident model weights (~1.2 GB each).
Kubernetes `replicas: 3` also needs `strategy: Recreate` or `maxSurge: 0`, because the default
rolling update runs two pods for the length of the rollout — the guard reads per-process env and
cannot see that.

**Alternatives.** Redis pub/sub (`redis.asyncio`) with each instance subscribing to a channel and
fanning out locally; Postgres `LISTEN/NOTIFY` (no extra service, already have Postgres, but
payload size limits apply); a broker (NATS/Redis Streams) if delivery guarantees are needed later.
Tracked as **P17** — bought when vertical scaling runs out, not before.

**Verdict.** ✅ Keep, now with the rule enforced instead of merely stated. The decision is *stay on
one process until scaling is actually planned*; what changed is that a misconfigured deploy now
says so in its first log lines rather than showing a broken conversation hours later. Revisit with
P17.


---

## 5. AI / NLP

### Q19. Why am I using local `transformers` pipelines instead of calling an LLM API?

**Decision.** Hugging Face `transformers` running in-process today, with everything about the
packaging already decided except *where the model lives* (see Q20 below and open question U4).

**Why.**
- No API key, no per-request cost, no vendor lock-in, and no data leaving the machine — for a
  learning/portfolio project that is a real advantage. The counterpart is that the API image
  carries the full ML stack, which is exactly the cost the M3 packaging decision (U4) weighs.
- Offline-friendly: once the weights are cached, the feature works without network access.
- Both tasks are well-served by small, specialised models; an LLM would be overkill for
  "positive/negative" and a chat digest.

**Trade-offs.** This was the heaviest part of the project:
- ~1.6 GB of weights for BART-large and a slow, memory-hungry first request (gap B5).
- Model loading happened at import, so a failure to load took the whole API down (gap A6).
- 1024-token input limit meant long transcripts failed (gap A2).
- No control over output quality beyond the prompt-less summary API.

**Decided regardless of packaging (M3) — and now implemented:** lazy loading behind a lock;
a much smaller model (`sshleifer/distilbart-cnn-6-6`, ~300 MB); input-length guards that chunk
long transcripts and truncate long single messages instead of returning a 500; results persisted
per message together with the model name and pinned revision. The one item still open is the
timeout around inference: a hosted model would need one, an in-process CPU pipeline is bounded by
the request itself.

**Trade-offs of the packaging options.**

| Option | Trade-off |
| --- | --- |
| In-process, lazily loaded, small model | simplest to ship; the API's memory profile stays hostage to the model |
| Separate `inference` container in the same Compose stack | clean isolation, one more service to build and monitor |
| Hosted inference API (HF Inference, Groq, OpenAI) | near-zero runtime footprint and better text quality; costs money, needs a key, sends data out |
| Extractive only (TextRank/`sumy`, no model) | instant, no weights; "summary" means "top sentences", though keyword extraction still works |

**Verdict.** ✅ **In-process, lazily loaded, small and pinned (M3).** The current row is the first
one, and the gap between it and the alternatives is now small: the weights are ~300 MB, they load
on first use, a failure degrades only the two model-backed endpoints, and swapping in a hosted API
is a change to `ai_utils.py` plus an `RUN_AI_EVAL=1` run (A7) rather than a rewrite. Deciding
*before* writing the code, as this entry originally asked, is what made that so.

### Q20. Should I replace `facebook/bart-large-cnn`?

**Decision.** Yes — it is a placeholder that outgrew its purpose.

**Why it is there.** It is the canonical "summarise this" model, so it was the obvious thing to
reach for when the analytics route was written.

**Trade-offs.** ~406M parameters, ~1.6 GB on disk, seconds per request on CPU, and it makes a
free-tier deployment impossible. For chat messages — short, informal, repetitive — a large
newswire-trained abstractive model is a mismatch.

**Verdict.** ✅ **Done (M3):** `sshleifer/distilbart-cnn-6-6` (~300 MB, roughly 2× faster on CPU),
pinned to an exact upstream revision (`AI_SUMMARY_REVISION`) and configurable, with map-reduce
chunking so the token limit is never reached (A2). No extractive fallback was added: when the
model cannot load the endpoint answers `503` with the reason (A6) instead of quietly returning
something that is not a summary. Chat messages are short and informal — a newswire-trained large
model was never the right fit, and the swap is now a one-line settings change.

### Q21. Why is `torch` pinned to the CPU wheel?

**Decision.** `torch==2.7.0` with `--extra-index-url https://download.pytorch.org/whl/cpu`
at the top of the root `requirements.txt`.

**Why.** Inference on a few short messages gains nothing from a GPU, the CPU wheel is an order of
magnitude smaller (~200 MB vs multiple GB of CUDA libraries), and `torch` is only needed for
in-process inference.

**Trade-offs.** The CPU build is slower per request for long inputs, and the inline
`--index-url` in the middle of the requirements file is a real pip footgun for the lines that
follow it (gap A5).

**Alternatives.** `onnxruntime` with an ONNX-exported model (smaller, faster on CPU, no torch
dependency at all); `llama.cpp`-style quantised inference for a small generative model; a hosted
API (Q19), which removes torch from the project entirely.

**Verdict.** ✅ Keep CPU-only. ⚠️ **Decided (M1):** the index flag moves to the top of the
consolidated requirements file (or becomes its own install step) so it stops switching pip's index
for the lines that follow it (gap A5). If the M3 packaging decision puts inference in its own
container, that image is where `torch` (or an ONNX runtime) lives — the API image then carries none
of it.

### Q22. Should I run sentiment in the browser with `transformers.js`?

**Decision.** No — sentiment runs server-side inside the API.

**Why.** Server-side keeps one implementation for all clients, keeps the rules (rate limits,
persistence, audit) in one place, and lets the result be stored alongside the message (gap D7).
Model weights are also cached once on the server instead of downloaded per browser.

**Trade-offs.** Every keystroke-level analysis costs a round-trip, and the server pays the CPU
and memory cost. Client-side would be instant and free for the server.

**Verdict.** 🔒 Deferred. If the product wants live sentiment while typing, `transformers.js`
with a small distilbert (a few MB quantised) is a reasonable *additional* path for previews only —
with the authoritative score still computed server-side and stored.

### Q23. Should the AI endpoints be asynchronous (background tasks or a queue)?

**Decision.** No — they are synchronous request/response endpoints today.

**Why.** With one message or one day of chat, inference is sub-second to a few seconds; a queue
would add infrastructure for no user-visible benefit.

**Trade-offs.** Under concurrency the CPU-bound inference occupies a threadpool worker while it
runs (see Q2), the request can time out on long inputs (A2), and identical work is repeated (A4).

**Verdict.** ✅ **Implemented (M3):** messages are scored at *write* time, in the same transaction,
and stored in `message_sentiment` with the model name and pinned revision (gaps D7, A4, A7) — so the
analytics read path (the timeline, A3) is a lookup and `tests/test_sentiment_persistence.py` fails if
a read ever runs inference. `/analytics/sentiment` stays an ad-hoc endpoint for arbitrary text,
answered from an `lru_cache` for repeats. Scoring runs in a worker thread, and a model that cannot
load costs the score rather than the message (A6). A real queue (Celery/RQ/arq) stays out of scope
until volume justifies it — with async SQLAlchemy in place, a `BackgroundTask` or a small worker is
enough for per-message scoring.

One detail was decided while implementing: the stored score is **not** attached to every message
payload. `GET /messages/` is the hot path (paginated, merged with socket frames), and a join there
would cost every page to save one small query; an author's *name* is fetched per author for the same
reason (Q49). Sentiment is read where it is aggregated — the timeline — and can be added to the feed
later if the UI ever shows a badge per message.

---

## 6. Frontend

### Q24. Why Vite + React (SPA) instead of Next.js?

**Decision.** A pure client-side SPA: Vite 7 + React 19 + React Router 7 in `BrowserRouter`
mode, talking to the FastAPI origin.

**Why.**
- The app is a private, auth-gated dashboard: there is nothing to server-render for SEO and no
  content anyone needs to see while logged out.
- Vite's dev server starts quickly with HMR, and `npm run build` produces a simple static bundle
  (271 kB JS / 86 kB gzipped with the query layer included, measured with `npm run build`).
- Deploying static files is cheap and cacheable; the API stays the only stateful component.
- No server-component or edge-runtime concepts to learn — the mental model is "one origin for
  static assets, one for JSON".

**Trade-offs.** The first paint needs the JS bundle; private routes are now guarded by
`RequireAuth`, while server state is owned by TanStack Query (Q28). The origin/configuration cost is
gone with the single-origin nginx/Vite setup (Q34, M1).

**Alternatives.** Next.js (SSR/RSC, file-based routing, API routes in one deployable — sensible
once a public/SEO surface exists); Remix / React Router framework mode (better data-loading
story, needs a server runtime); plain React + esbuild (fewer features, more wiring).

**Verdict.** ✅ Keep the SPA. 🔄 Revisit if the project needs a public landing page, shareable
server-rendered message permalinks, or SEO — with the caveat that a Next.js migration would
rename every page and change both the auth and the fetch patterns.

### Q25. Why Tailwind CSS 4 and not CSS Modules, styled-components or MUI?

**Decision.** Tailwind CSS 4 through the `@tailwindcss/vite` plugin, with a single
`@import "tailwindcss";` in `src/index.css` and utility classes inline in JSX.

**Why.** Fastest iteration loop with no context switching between files, no naming decisions, no
dead CSS, a tiny production stylesheet (6.4 kB / 2.1 kB gzipped), and no runtime style injection
(unlike CSS-in-JS).

**Trade-offs.** Long class strings in JSX (visible in `Chat.tsx` and `Analytics.tsx`); repeated
utility clusters that should become components (`<Button>`, `<Card>`); and no design tokens yet,
so colours are hard-coded class names (`bg-blue-600`, `bg-green-600`) rather than a theme.

**First step taken (M3):** the focus ring every control needs — `focus-visible` outline, width,
offset and colour — is one `.focus-ring` class in `index.css` (`@layer components`, `@apply`)
instead of four utilities repeated on every button and input (gap F12). That is the pattern the
rest of the clusters should follow.

**Alternatives.** CSS Modules (explicit, no build plugin, more files); styled-components/Emotion
(co-located styles, runtime cost, less popular in the RSC era); MUI/Chakra (fast to build with,
opinionated look, much bigger bundle).

**Verdict.** ✅ Keep Tailwind. ⚠️ Extract the repeated class clusters into small components and
move the palette into an `@theme` block so a rebrand or dark mode is one edit instead of a search
and replace.

### Q26. Should I keep `tailwind.config.js`?

**Decision.** No — it should be deleted (gap F7).

**Why.** Tailwind 4 configures itself through CSS: `@import "tailwindcss"`, `@theme` for design
tokens, and `@source`/`@config` for anything unusual. The Vite plugin handles content detection
automatically. The existing `tailwind.config.js` (with `content` globs) is a Tailwind 3 remnant
for a PostCSS setup that is not used — it would silently do nothing if someone added theme values
to it, which is worse than not having it.

**Trade-offs.** Anyone used to Tailwind 3 will look for the config file first, so the docs have to
say where tokens belong instead (the READMEs now do).

**Verdict.** ✅ **Done (M1/M2):** `tailwind.config.js`, the `tailwind:init` script and the unused
`@tailwindcss/postcss`, `postcss` and `autoprefixer` devDependencies are gone, and `axios` left the
dependency list in M2 when the client moved to `fetch` (Q27). Theme tokens belong in an `@theme`
block in `src/index.css` (M4, Q25).

### Q27. Should the client use `fetch` or axios?

**Decision.** Native `fetch` behind one thin, typed client module — implemented in
`chat_frontend/src/apiClient.ts` (gap **F14**). *(Changed after review: the code used axios with a
request interceptor until M2.)*

**Why.**
- `fetch` is built in, and everything axios provides here — `baseURL`, query params, a request
  interceptor — collapses into roughly 30 lines of wrapper now that the app is single-origin (Q34)
  and the base URL is simply the current origin.
- API errors arrive as `{ detail: ... }`; a wrapper is the natural single place to turn a non-2xx
  response into a thrown, typed error instead of doing it at every call site.
- One less runtime dependency to audit and keep in step with React 19 and Vite 7.
- With TanStack Query (Q28) owning caching and retries, interceptors stop being the centre of
  gravity — the query functions become the abstraction.

**Trade-offs.** Losing interceptors means the token and the 401 handling move into the wrapper;
cancellation needs an explicit `AbortSignal`, though TanStack Query supplies one automatically. Both
are one-time costs paid in a single file.

**Alternatives.** Keep axios (it works today); `ky` (tiny, fetch-based, hook-friendly); generate a
client from `/openapi.json` (`openapi-typescript` + `openapi-fetch`), which pairs neatly with
removing hand-written response types (gap F13's OpenAPI-generation follow-up).

**Verdict.** ✅ **Done (M2):** `src/apiClient.ts` implements `apiGet`/`apiPost`/`apiDelete` over
`fetch`, `src/api.ts` keeps the endpoint wrappers and returns plain data, and `axios` is out of
`package.json` (gap **F14**). TanStack Query (Q28/F16) now sits on top of the same wrappers.

### Q28. Should the client use TanStack Query instead of hand-rolled fetching?

**Decision.** TanStack Query. *(Changed after review: adopted now instead of "later"; the code then
used `useEffect` + `useState`.)*

**Why.**
- The biggest quality gaps on the pages are the *consequences* of hand-rolled fetching: no loading
  state, no error surface, no retries, no cache, and duplicate requests between pages (gaps F9, F6).
  A data layer fixes the cause instead of patching symptoms page by page.
- The WebSocket work (M2) needs a cache to reconcile pushed messages with fetched history — de-duping
  by `id` and refetching on reconnect is exactly what a query cache is for.
- `useMutation` + `invalidateQueries` turns "send a message, then refresh the feed" into a five-line
  operation and removes the manual `await getMessages()` refresh loop from `Chat.tsx`.
- It is a small dependency with first-class TypeScript types and devtools, which fits the strict
  TypeScript setup already in place.

**Trade-offs.** One more concept in the codebase (query keys, staleness, invalidation) for a
three-screen app, plus wiring a `QueryClientProvider` into `main.tsx` and moving fetch logic into a
`queries/` folder instead of inline effects.

**Alternatives.** SWR (smaller, similar); RTK Query (only if Redux Toolkit ever lands); keep manual
but standardise a `useApi` hook (fixes part of F9, none of the caching or invalidation problems).

**Verdict.** ✅ **Done (M2):** TanStack Query 5 owns server state (gap **F16**), mounted once in
`main.tsx` with the policy in `src/queries/client.ts` and the hooks in `src/queries/`.
`useInfiniteQuery` drives the keyset feed, `useMutation` drives the composer, delete and sentiment
analysis, and the daily summary is a lazily enabled query. One plan detail changed on contact:
invalidation was dropped in favour of writing the cached feed directly, because invalidating an
infinite query refetches every loaded page while the mutation response (or the socket echo, merged
by `id`) is already the authoritative row.

### Q29. Why `jwt-decode` to read the current user id on the client?

**Decision.** `AuthProvider` reads `jwtDecode(token).sub` once for UI attribution and owns the
validated token for the route guard, navbar and chat page.

**Why.** It avoids an extra `GET /users/me` call on page load and needs no additional state.

**Trade-offs.** The UI derives identity from a token it cannot cryptographically verify; the
API remains the authority for every protected request. The id format is still a frontend/backend
contract, but it is now centralized in the auth token helper.

**Alternatives.** Call `GET /users/me` after login and store the `User` (blocked today by gap
B2); decode *and* verify server-side on every request (which is what actually protects the data);
hold the profile in an auth context/provider so components stop decoding tokens themselves.

**Verdict.** ✅ Keep decoding for UI attribution, but keep it behind `AuthProvider`; it now owns
"who am I" for routes, navbar and chat. `/users/me` is fixed (B2), while server-side validation
remains the authority for protected data.

### Q30. Should I add a state manager (Redux, Zustand) or a component library?

**Decision.** No Redux or Zustand. A small `AuthProvider` owns the token/current user;
TanStack Query owns server state (Q28/F16).

**Why.** There is exactly one piece of cross-page state (the token/current user) and no
server-cache problem yet. Redux for three screens would be ceremony.

**Trade-offs.** Auth state is now shared deliberately, and the remaining page data is server state
owned by TanStack Query (F16) rather than a store. A full state library would still be unnecessary
for this screen count.

**Verdict.** ✅ Keep the small `AuthContext`; it owns the token, current user id, expiry and
logout (F4/F5). No Redux/Zustand. TanStack Query now covers server state (Q28/F16), and a component
library becomes worthwhile once modals, dropdowns and toasts appear (gap P5).

### Q31. Why is the WebSocket URL built by hand instead of using a library?

**Decision.** A pure URL helper (`chatSocketUrl()` in `src/realtime/protocol.ts`) combined with `react-use-websocket` v4.

**Why.** `chatSocketUrl()` resolves `ws(s)://` based on current page origin and keeps credentials out of the URL (gap S8). `react-use-websocket` provides battle-tested connection lifecycle, exponential reconnection backoff, and clean event unbinding.

**Trade-offs.** Using `react-use-websocket` adds a small dependency (~15 kB) but eliminates brittle manual reconnection loops, socket reference tracking, and memory leaks.

**Alternatives.** Hand-rolled `new WebSocket(...)` (fragile lifecycle, manually maintained timeouts); `socket.io-client` (requires matching backend protocol); `partysocket`.

**Verdict.** ✅ **Adopted in M2 (gaps S8, F11).** The `useChatSocket` custom hook wraps `react-use-websocket` to manage protocol concerns: first-frame auth, heartbeat verification (ping/pong), optimistic/confirmed send correlation via `client_id`, and transparent REST fallback.

---

## 7. Deployment & operations

### Q32. Why did the Render blueprint go away?

**Decision.** `render.yaml` has been **removed**. Deployment is container-based (Docker Compose, Q33)
and no PaaS-specific configuration is checked in for now. *(Changed after review.)*

**Why.**
- The blueprint could not boot the app: `uvicorn main:app` referenced a `main.py` that does not exist
  at the repository root (the real module is `chat_backend.main`), and `buildCommand` installed the
  root `requirements.txt`, which is missing `uvicorn`, `psycopg2-binary` and `python-multipart`
  (gaps O1, O2). A deploy config that cannot deploy is worse than none, because it advertises a
  supported path that does not exist.
- `generateValue: true` for `SECRET_KEY` rotated the signing key on every deploy — logging every user
  out — and made the value impossible to share between services (gap O9).
- Free-tier instances sleep, which fights an API whose startup loaded a 1.6 GB model (gaps B5, A6):
  the platform choice and the model choice were working against each other.
- Pinning the project to one provider's YAML is not a portability strategy. A container image is:
  the same artefact runs locally, in CI and on any host, and changing providers stops being a
  repository change.

**Trade-offs.** There is no longer a zero-config push-to-deploy path: shipping now means running a
container somewhere (a small VPS, a container host, or a PaaS re-added later). That is more
operational work in exchange for a deployment that is reproducible and matches the code.

**Alternatives.** Patch the blueprint in place (a few lines) and keep Render as an option; re-add a
PaaS blueprint once the app is containerised anyway, since Compose and most PaaS platforms can share
a single Dockerfile.

**Verdict.** ✅ **Decided.** No PaaS blueprint for now — Docker Compose is the deployment unit (Q33).
Re-adding a managed platform later is a ~20-line file pointing at the same image, and that is the
point: the image is the contract, not the YAML.

### Q33. Should I add Docker?

**Decision.** Yes — Docker + Docker Compose becomes the primary way to run and deploy the app.
*(Changed after review: previously "not yet".)*

**Why.**
- It makes the README true: `docker compose up` yields a database, an API with migrations applied,
  and the web client, with no host-specific setup.
- It isolates the two environments that matter in one file — a disposable `db` service for
  development data (Q10) and production-shaped `api`/`web` services.
- It removes a whole class of "works on my machine" bugs from a project with native dependencies
  (`asyncpg`/`psycopg2`, `torch`), which is currently a real onboarding tax.
- The same image is the deployment artefact (Q32), so local and production stop diverging.

**Trade-offs.** Images add build time and a layer to learn; an inference image is large unless it is
split out (U4); and Compose is a development convenience, not a production orchestrator — a public
deployment still needs TLS termination, secret injection and backups.

**Alternatives.** Stay venv-only (rejected: onboarding and parity suffer); devcontainers alone
(helps the editor, not the deploy); Kubernetes (wildly disproportionate at this size).

**Verdict.** ⚠️ **Decided (M1):** ship `docker-compose.yml` with `docker/api.Dockerfile` and
`docker/web.Dockerfile`; the `api` container runs `alembic upgrade head` before Uvicorn starts; a
separate `inference` image is added only if U4 says so. Tracked as gap **O13**.

### Q34. Should the SPA be served by FastAPI, or from a separate static host?

**Decision.** **Single origin.** In development the Vite dev server proxies API and WebSocket traffic
to FastAPI; in a shipped build the static bundle is served on the same origin (by the API or by the
`web` container). *(Changed after review: previously "separate origins in dev, collapse at deploy
time".)*

**Why.**
- It deletes a class of problems instead of configuring them: the CORS wildcard (gap S4), the
  hard-coded API and WebSocket URLs (gap F2), and the missing frontend deployment story (gap O4) all
  disappear in one move.
- Cookies become viable (Q5), which is what an `HttpOnly` session needs later — cross-origin
  credentials are precisely why that option was ruled out before.
- Development keeps HMR: a proxy block in `vite.config.ts` is a few lines, and the browser still sees
  one origin.
- There is no real cost here: the SPA and the API ship from one repository already, and nothing else
  consumes the API yet.

**Trade-offs.** The frontend build becomes part of the deployment artefact (an API image or a sibling
container that must serve the same origin), so a JS-only change rebuilds the web output too. A future
public API for third parties would want its own origin, at which point explicit CORS returns.

**Alternatives.** Keep separate origins with a corrected, explicit CORS allow-list (more config, two
URLs to keep in sync); a reverse proxy/edge routing `/api` and `/` to two services — the
production-grade version of the same single-origin idea, useful once a CDN sits in front.

**Verdict.** ✅ **Decided and implemented (M1).** In development the Vite dev server proxies the API
and `/ws` to `http://127.0.0.1:8000`; in production the nginx `web` container serves the built
bundle and reverse-proxies `/users`, `/messages`, `/analytics`, `/ws` and the health routes to
the `api` container, so the browser sees one origin (`http://localhost:8080`). `CORSMiddleware` is
not needed and the hard-coded base URLs are gone. Closed gaps **F2**, **F15**, **S4** and **O4**.

### Q35. Should I add CI (GitHub Actions)?

**Decision.** Yes. GitHub Actions runs backend and frontend checks on pushes to `main` and pull
requests (gap O6, now closed).

**Why.** With one contributor and manual verification, the immediate payoff was low.

**Trade-offs.** CI adds a small maintenance cost and requires a PostgreSQL service for backend
runs, but it makes migrations, ownership rules and frontend regressions visible before merge.

**Alternatives.** GitHub Actions (free minutes for public repos, service containers for Postgres
— the obvious choice); pre-commit hooks for the fast subset (lint/format only); Render's own build
as the only gate (too late and too coarse).

**Verdict.** ✅ **Implemented (M1).** The workflow runs backend ruff, migrations against a clean
PostgreSQL service and pytest, plus frontend npm ci, lint, Vitest and production build. The
backend suite has already caught migration and ownership regressions locally; gap **O6** is closed.

---

## 8. Project structure & conventions

### Q36. Why a monorepo with `chat_backend/` and `chat_frontend/` at the root?

**Decision.** One repository, two top-level directories, one shared `.env` at the root, and a single
compose stack (M1) as the deployable.

**Why.** The frontend and backend change together (an API change usually needs a client change),
so a single commit can keep them consistent; one clone gets a running system; and the deploy
config lives next to the code it describes.

**Trade-offs.** Tooling for two ecosystems sits at the root, which is how two `requirements.txt`
files (Q15) and the env-var confusion (`VITE_API_URL` at the root instead of in
`chat_frontend/`, gap F2) happened. There is also no shared contract check between the two halves
— the types in `types.ts` are maintained by hand (gap F13's OpenAPI-generation follow-up remains).

**Alternatives.** A `packages/`-style workspace with per-app manifests (clearer boundaries, more
config); `apps/api` + `apps/web` (same idea, more conventional naming); two repositories
(decouples deploys, guarantees drift).

**Verdict.** ✅ Keep the monorepo. 🔄 Rename to `backend/`/`frontend/` (or `apps/*`) only when
something else is added — the current names are long but unambiguous, and `chat_backend` is
already baked into imports and Alembic.

### Q37. Why do some modules use `chat_backend.…` imports and others use `..`?

**Decision.** A mix: `main.py` and `routes/websocket.py` use absolute imports
(`from chat_backend.auth_utils import …`), while the other route modules use relative ones
(`from .. import models`). Both work, because the app is always imported as a package — as long as
it is started from the repository root.

**Why.** Incremental development: absolute imports came first (the more common style in FastAPI
examples), and relative imports followed naturally inside `routes/`.

**Trade-offs.** The inconsistency is a readability cost, and the run-from-the-root requirement is
a trap for deployment (`uvicorn main:app` from inside `chat_backend/` breaks — gap O1) and for
tooling that executes a module directly.

**Alternatives.** All-absolute (works regardless of entry point, needs the package on `sys.path`);
all-relative (self-documenting, but forbids running a file as a script); a `src/` layout with
`pip install -e .` (most robust, needs the `pyproject.toml` from gap T4).

**Verdict.** ⚠️ **Decided (M1):** standardise on absolute imports as part of the packaging change,
paired with `pyproject.toml` and an editable install (`pip install -e .`) so the package resolves
regardless of the working directory (gaps **T4**, **O1**). Until then, keep the "run from the
repository root" rule prominent — the README states it explicitly.

### Q38. Why one router file per resource rather than one big `main.py`?

**Decision.** `routes/users.py`, `routes/messages.py`, `routes/analytics.py`,
`routes/websocket.py`, each with its own `APIRouter`, registered in `main.py` via
`app.include_router(...)`.

**Why.** Each file owns a prefix and an OpenAPI tag, so `/docs` is grouped and every endpoint for
a resource is in one place. It also keeps `main.py` limited to app setup.

**Trade-offs.** Router files could accumulate business logic unless isolated into a service layer.

**Verdict.** ✅ **Implemented in M2 (gap B12).** Persistence operations are centralized in `crud.py` (`create_message`, `get_messages_for_user`, `delete_message`), while `realtime.py` houses connection tracking and frame builders. `routes/messages.py` and `routes/websocket.py` both call into `crud.py`, guaranteeing consistent validation, DB persistence, and realtime broadcasts.

### Q39. Why are Pydantic schemas separate from SQLAlchemy models?

**Decision.** `models.py` (ORM) and `schemas.py` (Pydantic v2, with `from_attributes = True`) are
distinct files using a `Base`/`Out`/`Create` naming scheme.

**Why.** The API contract and the table shape are genuinely different concerns: `UserOut` must
never expose `password_hash`, and `MessageCreate` must never accept `user_id` from a client.
Keeping them apart makes that explicit and lets each side evolve independently.

**Trade-offs.** Duplication — a new column means touching `models.py`, `schemas.py` and a
migration. It also invites drift; unused schemas should be removed once their first consumer is
identified. The routes deliberately use Pydantic response models rather than returning ORM objects
directly, so OpenAPI and validation stay explicit.

**Alternatives.** `SQLModel` (one class, less boilerplate, couples API shape to table shape);
return ORM objects directly (an earlier prototype choice); Pydantic with explicit field
allow-lists only.

**Verdict.** ✅ Keep them separate — the `password_hash` exclusion alone justifies it. The
message routes now use `MessageOut` and `MessageCreate` has a bounded text field (B3); unused
schemas can be removed when their first consumer is identified.

### Q40. Should I keep the commented-out code?

**Decision.** No. Commented-out code is removed; Git history is the archive, and the gaps document
records the remaining implementation work.

**Why it happened.** Each block was "temporarily disabled to get something working" — normal
during exploration.

**Trade-offs.** A reader cannot tell whether a block is a deliberate fallback or forgotten work.
The WebSocket auth block is the dangerous case: it makes the endpoint *look* protected when it is
not (gap S1).

**Verdict.** ✅ **Done.** The dangerous WebSocket-auth and exception-handler blocks are gone, and
remaining unfinished work is tracked in the gaps document rather than left as commented code.

---

## 9. Undecided / open questions

These are decisions that have **not** been made yet, with the options and the information needed
to choose. Writing them down is the point: an undocumented "we will figure it out later" is how
the two-`requirements.txt` problem and the two-tailwind-config situation happened.

| # | Open question | Options | What would settle it |
| --- | --- | --- | --- |
| U1 | **What is the conversation model?** A global timeline today (gap P1) | global timeline · rooms/channels · 1:1 DMs · threads | The product intent. If it is "portfolio piece", rooms are the most impressive; if it is "WhatsApp clone", DMs are mandatory. Either way it reshapes `messages` and every query. |
| U2 | **Pagination style** | ✅ keyset by `(timestamp, id)` implemented in B10 and the load-older UI is live; an opaque cursor is deferred until needed | The API uses a timezone-aware `before` + `before_id` cursor. F6 also adds owner-only delete UI and `id`-based REST/socket de-duplication. |
| U3 | **Where does sentiment get computed?** | on demand (today) · at write time · background worker | Whether a message always needs a score. Write-time scoring (gap D7) removes latency and enables a real dashboard (P12). |
| U4 | **Where does NLP inference run?** (Q19) — the only decision still open | in-process + lazy + small model · separate `inference` container · hosted API (HF Inference / Groq / OpenAI) · extractive only, no model | Which matters more: keeping every byte in-house, or a small API image with better summaries. It also decides whether the Compose stack gets a third service and whether an API key is needed at all. Everything else about the AI layer is already settled (Q19/Q20/Q23). |
| U5 | **Identity beyond username/password** | email + verification · OAuth (Google/GitHub) · both | Whether password reset (P9) and account recovery are considered MVP. |
| U6 | **Attachments** | Supabase Storage · S3/R2 · none | Whether files are part of the product. If yes, upload validation and storage cost modelling are needed up front (P7). |
| U7 | **Observability stack** | structured logs only · logs + Sentry · OpenTelemetry traces | Whether this needs to be debuggable in production by someone other than the author (gap O5). |
| U8 | **Caching layer** | none · in-process (`lru_cache`/`cachetools`) · Redis | Whether AI results, user lookups and rate limits need shared state (Q18, U3). Redis solves several of these at once if the app scales horizontally. |
| U9 | **Search implementation** | Postgres FTS (`tsvector` + GIN) · `pg_trgm` fuzzy · dedicated engine (Meilisearch/OpenSearch) | Result quality expectations. Postgres FTS is almost certainly sufficient for chat messages (gap P4). |
| U10 | **Scale target** | single-instance demo · hundreds of users · "real product" | This question unlocks the rest: it decides whether the in-memory `ConnectionManager` (Q18), `create_all()` (Q13) and free-tier hosting (Q32) are acceptable or fatal. |

---

## 10. Post-review decisions

These entries exist because a review pass changed a decision. They are the "what we chose to do
about it" half; the [dissent outcomes](#review-dissents--outcomes) below list what was accepted and
what was not.

### Q41. Why Docker Compose instead of a platform blueprint?

**Decision.** `docker-compose.yml` is how the project is run and deployed; the previous `render.yaml`
is gone (Q32).

**Why.**
- The image is the contract: the same artefact runs in development, in CI and wherever it is hosted,
  so "works locally" means something again.
- It makes the README's first command true — `db` + `api` (with migrations applied) + `web` — instead
  of a sequence of manual steps nobody reproduces exactly.
- It absorbs the native-dependency onboarding tax (`asyncpg`, `torch`) instead of documenting it.
- Compose doubles as the test harness: CI and local runs get the same PostgreSQL service (Q43/T5).

**Trade-offs.** More moving parts than a venv; images cost build time; and Compose is not a
production orchestrator — no TLS termination, no secret management, no backups. It is the deployment
*unit*, with a reverse proxy or host in front of it.

**Alternatives.** A PaaS with a fixed blueprint (rejected for now — Q32); per-service Dockerfiles
without Compose (more manual wiring); devcontainers only (helps editors, not deploys).

**Verdict.** ✅ Decided (M1). Gap **O13** lists the files, and the README's definition of shippable
requires `docker compose up` to work end to end.

### Q42. Why keep a WebSocket that does not work yet?

**Decision.** Keep `WS /ws/chat` in the codebase, visible in the docs, and finish it in M2. The
review recommended commenting it out or deleting it; that recommendation was **rejected**.

**Why.**
- Realtime delivery is a product requirement, not an experiment: a chat app that cannot push a
  message to another client is missing its defining feature. Hiding the code would not change that —
  it would only hide the gap.
- The pieces already exist and are wired together (client helper, route, `ConnectionManager`), so the
  remaining work is finishable rather than starting over: authenticate, persist, broadcast, reconnect.
- Keeping it turns the gap into the plan: M2 sits immediately after the shippable core, so the window
  in which the transport is incomplete is deliberate, short and visible.

**Trade-offs and guardrails.** A half-built feature becomes a liability the moment it *looks*
finished, so keeping it comes with rules:

- the status table and the protocol section describe it as an echo endpoint and itemise exactly what
  is missing — handshake auth (S1), persistence (B1), fan-out (B1), JSON contract (F3), token in the
  query string (S8);
- nothing else depends on it: REST stays the source of truth for history, so an incomplete socket
  degrades rather than breaks;
- the token leaves the query string before anything else touches it (S8) — an unauthenticated socket
  in public is the one outcome worse than deleting the endpoint.

**Alternatives.** Delete or comment it out until M2 (rejected: loses momentum and hides the gap);
adopt Socket.IO for free reconnection and rooms (deferred — Q17 keeps the hand-rolled server while
there is one broadcast target); Supabase Realtime (deferred with the hosted-Postgres decision, Q10).

**Verdict.** ✅ Decided. Kept, labelled honestly, and finished in M2 (gaps S1, B1, F3, F11, S8).

### Q43. Why pytest + httpx and Vitest + React Testing Library?

**Decision.** Backend: `pytest` + `pytest-asyncio` with `httpx.ASGITransport` against a real
PostgreSQL service. Frontend: Vitest + React Testing Library + jsdom; both suites run in CI.
MSW handlers (`src/test/handlers.ts`) back page-level tests that run the real
`apiClient`/query stack instead of `vi.mock`-ing the api module (T5).

**Why.**
- `ASGITransport` tests the actual app object with no live server and no port, which keeps the suite
  fast and parallel-safe, while a real PostgreSQL service keeps the tests honest about the dialect
  production uses.
- Transaction-per-test with rollback gives isolation without truncating tables or imposing test
  ordering.
- Vitest reuses the Vite config and transform pipeline already in place, so there is no second
  build setup to maintain. The first frontend tests cover the auth boundary without needing a
  network mock; MSW can be added when the client migrates to `fetch`.

**Trade-offs.** A database-backed suite is slower than a mocked one and needs a service container in
CI. MSW mocks can drift from the real API unless they are generated from `/openapi.json` — which is
why generating the remaining types from OpenAPI (F13 follow-up) pairs well with it.

**Alternatives.** `unittest` (no plugin ecosystem); SQLite for tests (dialect divergence plus a
different async driver); Cypress/Playwright end-to-end only (valuable later, too slow and too coarse
as the first line of defence); Jest (needs a separate transform config next to Vite).

**Verdict.** ✅ Implemented: backend tests are in place (55 passing), the frontend has 52
Vitest tests across 10 files (auth boundary, chat UI, realtime hook, wire protocol, MSW
page-level flows, CSP baseline), and CI runs both suites. Gaps T1, T2 and T5 are closed.

### Q44. Why is the AI packaging still an open question?

**Decision.** Everything about the AI layer is decided except *where* it runs — U4.

**Why.**
- The technical constraints are independent of packaging, so that work can start without the answer:
  lazy loading, a smaller model, length guards, inference timeouts, persisted results (Q19/Q20/Q23).
- The packaging choice trades two goods against each other — "no data leaves the machine, no keys, no
  vendor" versus "a tiny API image, better summaries, nothing extra to keep alive". That is a product
  value judgement rather than a technical one.
- It has deployment consequences too: a third Compose service, an API-key secret, or a persistent
  model-cache volume. Deciding it late would invalidate parts of the deployment documentation.

**Trade-offs of waiting.** M3 cannot be finished until it is answered, and until then the API keeps
carrying whatever the current in-process code needs.

**Verdict.** 🔬 Open (U4). Default if no explicit choice is made: **in-process, lazy-loaded, small
model**, because it keeps the stack at two services and needs no credentials.

### Q45. Why is mypy configured non-strict with two plugins?

**Decision.** `mypy` runs in non-strict (default) mode with `check_untyped_defs`
and `ignore_missing_imports`, plus the `pydantic.mypy` and
`sqlalchemy.ext.mypy.plugin` plugins — over the same trees as ruff
(`chat_backend`, `tests`, `alembic`), pinned in `requirements.txt` and run in
CI next to ruff.

**Why.**
- The codebase was written without a type-checker in the loop; strict mode would
  have produced a wall of `Any`-related noise that teaches nothing. The default
  mode still catches what matters here: wrong argument types, mismatched returns
  (it found `/health/ready` annotated `JSONResponse` but returning a dict), and
  mistakes inside unannotated functions.
- The pydantic plugin lets `Settings()` be constructed without listing its
  environment-loaded fields as arguments; the SQLAlchemy plugin understands
  `Mapped[int] = Column(Integer, …)`, so `user.id` checks as `int` instead of
  `Column[int]` — that one change removed a dozen false errors across the routes.
- The models gained `Mapped[]` annotations while keeping their `Column(...)`
  values, so the schema and the migration are untouched (verified: metadata
  nullability matches the initial revision column for column).

**Trade-offs.** Two plugins tie mypy to their hosts' compatibility windows, so
`mypy` is the pin to keep current. Unimportable third-party types are trusted
(`ignore_missing_imports`) — the usual cost of adopting a checker after the fact.

**Alternatives.** Strict mode plus mass `# type: ignore` (unreviewable); rewriting
the models to `mapped_column(...)` (a schema-adjacent refactor that belongs with
D4/D6); skipping mypy (T3 stays open and type errors stay invisible).

**Verdict.** ✅ Implemented in M1: `mypy` reports zero issues over 27 files and
runs in CI alongside ruff (gaps T3, O6).

### Q46. Why JSON logs with request ids instead of an error-tracking service?

**Decision.** The API logs one JSON object per line (stdlib only: a
`JsonFormatter` and one root handler), every request gets an `X-Request-ID`
that is echoed in the response and stamped on its access line, and the 500
handler returns the same id in the body. Sentry/OpenTelemetry is deferred until
the app has a deployment target (U7).

**Why.**
- The immediate need is correlation, not aggregation: given a user's report of a
  failed request, the id finds the matching access line and — for a 500 — the
  traceback. That works with `docker logs`, CI output and any future log shipper.
- JSON on stdout is what every container host already parses; adding a vendor SDK
  before the app is deployed would add a dependency, a DSN secret and a network
  call with no consumer for the events.
- The middleware accepts a client's `X-Request-ID` only when it is header-safe
  (`[A-Za-z0-9._-]{1,64}`) and replaces it otherwise, so a proxy can thread its
  own id through without a header being able to inject into the log stream.
  Health probes log at DEBUG so `/health` polling does not drown real traffic.

**Trade-offs.** No dashboards, alerts or release tracking — the "error tracking"
half of O5 stays open until U7 is answered. Structured logs are only as good as
the retention of wherever they run.

**Alternatives.** Sentry now (nowhere to send events yet); OpenTelemetry traces
(overkill before there is a second service); plain text logs (unparseable once a
host starts parsing them).

**Verdict.** ✅ Implemented in M1: JSON request logging with request-id
correlation, covered by `tests/test_observability.py`; external error tracking is
an explicit follow-up tied to U7 (gap O5).

### Q47. When a user is deleted, what happens to their messages?

**Decision.** They are deleted with them: the FK carries
`ON DELETE CASCADE`, the relationship uses `passive_deletes=True`, and
`DELETE /users/me` is the endpoint that triggers it (gap D4).

**Why.**
- Every read is author-scoped (`user_id == current_user.id`), so an orphaned
  message is unreachable by construction — keeping the rows would store data
  nobody can ever see, which is the opposite of what a "delete my data" request
  asks for.
- The alternative — nullable `user_id` and keep the rows — only makes sense if
  the feed becomes global or shared (P1/U1). If that ever lands, the policy can
  be revisited with a real use case instead of a hypothetical one.
- `passive_deletes=True` makes deletion one `DELETE` statement: the ORM never
  loads the messages just to delete them, and the database does the work in the
  same transaction it is already in.

**Trade-offs.** Deletion is irreversible — there is no soft-delete tombstone.
For a solo portfolio app without a retention policy that is the right default;
a production service would add a grace period first.

**Alternatives.** Keep messages with `user_id` nullable (unreadable orphans
today); soft-delete both user and messages (needs a `deleted_at` on two tables
and filters on every read — deferred with D5).

**Verdict.** ✅ Implemented in M2: model + revision `f4e5d6c7b8a9` +
`DELETE /users/me`, with the cascade asserted in `tests/test_account_deletion.py`.

### Q48. How was the CSP split between API, docs and SPA?

**Decision.** Three cooperating policies instead of one (gap S11): the API
answers JSON with `default-src 'none'` (plus nosniff/frame/referrer/HSTS), the
Swagger/ReDoc paths get a narrow policy allowing their CDN and inline
bootstrap, and the SPA carries a permissive-by-comparison meta tag in
`index.html` that nginx tightens with a stricter header at serve time.

**Why.**
- One policy cannot serve all three: `default-src 'none'` breaks `/docs`, while
  Swagger's allowances on JSON responses would be pointless noise — so the CSP
  follows the path, not the app.
- The SPA meta tag is what a host without headers (the Vite dev server, any
  static bucket) still inherits, and it must permit the dev React Refresh
  preamble's inline script — hence `script-src 'self' 'unsafe-inline'` there.
  The built bundle has no inline scripts, so the nginx header omits
  `unsafe-inline` and, where both apply, both are enforced: production ends up
  with the strict one.
- The nginx CSP lives *inside* the SPA `location`. At server level it would
  also attach to proxied API responses, intersecting FastAPI's Swagger CSP and
  breaking `/docs` in production — a real trap, given nginx `add_header`
  inheritance rules.

**Trade-offs.** The meta tag alone still allows inline scripts (dev has to
work), and `frame-ancestors` is ignored in meta tags, so clickjacking
protection depends on the header being present. HSTS is emitted over plain
HTTP too — inert there by spec, effective only once TLS terminates.

**Alternatives.** A single strict CSP everywhere (breaks Swagger); no SPA CSP
until a host provides one (leaves the dev/static path unhardened); a nonce-based
docs CSP (would require patching FastAPI's `/docs` template for no gain on a
JSON API).

**Verdict.** ✅ Implemented in M2: `SecurityHeadersMiddleware`, the index.html
meta tag and the nginx header set, covered by `tests/test_security_headers.py`
and `src/test/indexHtml.test.ts`.

### Q49. Should the feed carry user objects, or look names up per author?

**Decision.** One `GET /users/{user_id}` per distinct author, cached in the browser under
`["users", "profile", <id>]`; the message payload stays exactly what it is (`id`, `user_id`,
`text`, `timestamp`).

**Why.** `GET /messages/` is the hot path: keyset-paginated, merged with socket frames, already
scoped to the reader. Joining a user row onto every message would add work to every page and invite
an N+1 (`MessageWithUser` has been in `schemas.py` since M1, unused, for exactly this reason and is
still not returned). Attribution needs one field — a name — and a name changes rarely, so caching it
per author beats duplicating it per message: two messages by the same author cost one request
(`useQueries`), and a message that arrives over the socket is named on the next render with no extra
wiring.

**Trade-offs.** An extra request per distinct author, and a visible fallback: while the profile is in
flight — or when it 404s, because the account was deleted — the feed shows `User <id>`. Writes stay
simple: nothing has to be invalidated when someone renames, because the feed never held a copy.

**Alternatives.** Return `MessageWithUser` from the list (rejected above); denormalise the name onto
each message (stale the moment it changes); add a batch endpoint (`POST /users/lookup` with a list of
ids) — the honest next step if the number of distinct authors in one view ever grows large.

---

### Q50. How is credential brute-forcing stopped?

**Decision.** A sliding-window counter per client address held in the process, guarding
`POST /users/login` (10 attempts / 5 min) and `POST /users/register` (5 / hour), alongside a password
policy on registration. No new dependency, and no reverse-proxy rule.

**Why.** S6 named three failure modes: unbounded credential input, a hammerable login, and open
registration. The input side is validation — `UserCreate` carries the bounds (username 3–32 characters
of `[A-Za-z0-9._-]`, password at least 8 characters and at most 72 *bytes*), and the answer is a `422`
that names the field. The byte rule is not cosmetic: bcrypt hashes at most 72 bytes, and where
`passlib` truncated the remainder silently (so two different passwords sharing a 72-byte prefix
were the same credential — reproduced against passlib 1.7.4 + bcrypt 4.0.1), `bcrypt 5.0.0`
refuses longer input outright. Argon2id writes hashes today (S10), but the cap stays so that the
credentials the legacy bcrypt rows were built from remain within what both hashers accept.

For the `429` side, the two options the gap suggested were both declined. `slowapi` adds a dependency
(and `limits` behind it) for what `chat_backend/ratelimit.py` does in one class, and an nginx
`limit_req` rule would live outside the application: not exercisable by `pytest`, and needing an edge
reload to tune. The counter is also the *in-process* branch of the shared-state question (U8), which
keeps the decision reversible — the surface is one `retry_after(key)` call, so a Redis-backed
implementation replaces the class without a route changing.

**Trade-offs.** Documented in the module docstring rather than implied: state is per worker, so N
uvicorn workers multiply each limit by N (exact at one worker, which is the Compose default); the
bucket key trusts `X-Real-IP`, which is only safe because nginx *rewrites* that header and the `api`
service publishes no port; and the table is capped at 10 000 live keys and **fails open** past that,
because a limiter that starts refusing traffic is the denial of service it exists to prevent.

**Alternatives.** `slowapi` and an nginx `limit_req` (both above); Redis-backed counters, which are
the right answer once there is more than one worker (U8); counting only *failed* attempts, rejected
because it bounds nothing — the request still reaches the database and the hasher, so the endpoint's
cost stops being limited by the rate.

---

## Review dissents — outcomes

A review pass over `main` produced a list of twelve recommendations (R1–R12 — numbered with `R`
so they cannot be confused with the `D#` gap IDs). This is what
happened to each one, so the document records disagreements as well as agreements.

| # | Recommendation | Outcome | Reflected in |
| --- | --- | --- | --- |
| R1 | Get NLP inference out of the web process; smaller model, lazy loading, persisted results | **Accepted** | Q19, Q20, Q23 rewritten; gaps B5/A1/A4/A6/A7; M3 |
| R2 | Delete (or comment out) the unfinished WebSocket until it is real | **Rejected** — keep it and make it real soon | Q16, Q42 record the decision; M2 is dedicated to it; the README labels it an echo endpoint until then |
| R3 | Remove `create_all()` and ship a real initial migration | **Accepted** | Q13 decided for M1; gaps D1/D2/B9/D11 |
| R4 | Run Postgres locally in Docker instead of developing against a shared hosted database | **Accepted** | Q10 rewritten; gap O13 |
| R5 | Collapse to a single origin now rather than at deploy time | **Accepted** | Q34 rewritten; gaps S4/F2/F15/O4 |
| R6 | Decide async vs sync deliberately (async preferred), before the WebSocket work | **Accepted** — async SQLAlchemy | Q2 rewritten; gap B13; M1 sequencing |
| R7 | Adopt TanStack Query now instead of "when rooms land" | **Accepted** | Q28 rewritten; gaps F16/F9/F6 |
| R8 | Treat `localStorage` as conditional on fixing the WebSocket token and CORS first | **Accepted** | Q5 verdict rewritten; gap S8 in M2, cookie migration in M4 |
| R9 | Swap `python-jose` for `PyJWT` | **Accepted** | Q8 rewritten; gap B14 |
| R10 | Consider dropping axios in favour of `fetch` | **Accepted** | Q27 rewritten; gap F14 |
| R11 | Raise the AI and deployment items in the priority order | **Accepted** | Milestone tables in the README; gap priority table reframed around milestones |
| R12 | Drop the LICENSE "gap"; move minimal auth tests into the first milestone | **Accepted** | O7 closed as not-a-gap; T1/T5 scheduled in M1 |

Decisions taken alongside these, in the same review: **Docker + Compose adopted** (Q33),
**the Render blueprint removed** (Q32), **a test suite adopted** (Q43), and **CI adopted** (Q35).

> Keeping D2 rejected is deliberate: the project wants a working realtime layer, not a hidden one.
> What the review changed instead is the *honesty* around it — the status table, the README section
> and the milestone plan all state plainly that the socket echoes today and becomes a real channel
> in M2.

---

## Decision log

A one-line summary of where every decision stands. Update this table when a verdict changes —
that is the signal to re-read the corresponding section.

| # | Decision | Status | Milestone | Ref |
| --- | --- | --- | --- | --- |
| Q1 | FastAPI for the API layer | ✅ keep | — | — |
| Q2 | Async SQLAlchemy (`asyncpg` + `AsyncSession`) | ✅ done | — | B13 |
| Q3 | Stay on FastAPI, no Django port | 🔒 deferred | — | — |
| Q4 | Stateless JWT auth | ✅ keep | — | B6, F5, S7 |
| Q5 | In-memory access token + `HttpOnly` refresh cookie (was `localStorage` short term) | ✅ done | M4 | S9, S8 |
| Q6 | `pwdlib`: argon2id writes, bcrypt verifies legacy hashes | ✅ done | — | S10 |
| Q7 | `passlib` removed; the `bcrypt<4.1` stopgap retired with it | ✅ done | — | S10 |
| Q8 | PyJWT replaces `python-jose` | ✅ done | — | B14 |
| Q9 | Refresh tokens + server-side logout | ✅ done | M4 | S7 |
| Q10 | Postgres in Compose for dev; managed instance when hosted | ✅ decided | M1 | O13 |
| Q11 | Drop the unused `supabase` dependency | ✅ done | — | D8 |
| Q12 | SQLAlchemy ORM (now async) | ✅ keep | — | D3, D4 |
| Q13 | Alembic is the only writer of DDL | ✅ done | — | D1, D2, B9, D11 |
| Q14 | Integer primary keys | ✅ keep | — | — |
| Q15 | One pinned requirements file + `pyproject.toml`; `uv` later | ✅ done | — | D8, T4 |
| Q16 | WebSockets for realtime — kept and finished | ✅ decided | M2 | S1, B1, F3 |
| Q17 | Hand-rolled `ConnectionManager` | ✅ keep | — | P1, P2, P16 |
| Q18 | In-memory broadcast, single instance — pinned and guarded | ✅ decided | M4b | N5, U10, P17 |
| Q19 | NLP off the request critical path | ✅ done | M3 | A1, B5, A6 |
| Q20 | Replace `bart-large-cnn` with a distilled model | ✅ done | M3 | A1, B5 |
| Q21 | CPU-only torch; move the index flag to the top | ✅ keep | M1 | A5 |
| Q22 | No client-side sentiment | 🔒 deferred | — | — |
| Q23 | Sentiment at write time, not a queue | ✅ done | M3 | A4, D7 |
| Q24 | SPA over SSR | ✅ keep | — | F4 |
| Q25 | Tailwind CSS 4; add design tokens | ✅ keep | M4 | — |
| Q26 | Delete `tailwind.config.js` and the unused CSS deps | ✅ done | — | F7 |
| Q27 | `fetch` replaces axios | ✅ done | — | F14 |
| Q28 | Adopt TanStack Query now | ✅ done | — | F16 |
| Q29 | Keep `jwt-decode`; centralize identity in `AuthProvider` | ✅ done | — | B2, F4, F5 |
| Q30 | No state library; use a small `AuthContext` | ✅ done | — | F4, F5, P5 |
| Q31 | Raw socket now; hook wrapper once reconnect lands | 🔄 revisit | M2 | F11 |
| Q32 | PaaS blueprint removed; containers instead | ✅ decided | M1 | O1, O2, O9 |
| Q33 | Docker + Compose adopted | ⚠️ change | M1 | O13 |
| Q34 | Single origin (Vite proxy + nginx `web`) | ✅ done | — | S4, F2, F15, O4 |
| Q35 | CI on every push | ✅ done | — | O6 |
| Q36 | Monorepo layout | ✅ keep | — | — |
| Q37 | Absolute imports + editable install | ⚠️ change | M1 | T4, O1 |
| Q38 | Router-per-resource layout; add a service layer | ✅ keep | M2 | B12 |
| Q39 | Pydantic schemas separate from models; use them | ✅ keep | M1 | B3 |
| Q40 | Remove all commented-out code | ⚠️ change | M1 | S1, B11 |
| Q41 | Docker Compose over a platform blueprint | ✅ decided | M1 | O13 |
| Q42 | Keep the unfinished WebSocket and finish it | ✅ decided | M2 | S1, B1, F3 |
| Q43 | pytest/httpx + Vitest/RTL as the test stack | ✅ both suites in CI | — | T1, T2, T5 |
| Q44 | Where NLP inference runs | 🔬 open — in-process today | M3 | U4 |
| Q45 | mypy non-strict + pydantic/SQLAlchemy plugins | ✅ done | M1 | T3, O6 |
| Q46 | JSON logs + `X-Request-ID` now; Sentry when deployed | ✅ decided | M1 | O5, U7 |
| Q47 | User deletion cascades their messages | ✅ decided | M2 | D4 |
| Q48 | CSP split: strict API, Swagger exception, SPA meta + nginx header | ✅ done | M2 | S11 |
| Q49 | Author names looked up per author, not carried on every message | ✅ done | M3 | F10 |
| Q50 | In-process per-IP rate limit on login/register + a registration password policy | ✅ done | M3 | S6 |

---

## How to use this document

1. Before adding a dependency or a service, search this file for that technology. If it is already
   discussed, follow the existing verdict — or write down why it is being reversed.
2. When a verdict changes, update the entry **and** the decision-log row. A stale verdict is worse
   than no verdict.
3. When a new decision is made, add an entry in the same shape (Decision / Why / Trade-offs /
   Alternatives / Verdict) rather than leaving it buried in a commit message.
4. Items referenced as "gap X" point at
   [`gaps_and_improvements.md`](gaps_and_improvements.md), which tracks the *work*; this document
   tracks the *reasoning*.

**Last reviewed:** commit `ca7932c` (`main`) — 50 questions, 10 open items.
