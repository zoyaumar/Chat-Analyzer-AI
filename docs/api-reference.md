# API reference

Every route, its authentication, its request shape, its response shape and its failure modes, plus
the WebSocket wire protocol. This is the reference half of the project: read
[Getting started](../README.md#getting-started) first if you have not already run it.

Everything is served from one origin (see [Architecture](../README.md#architecture)); the examples
below use `http://127.0.0.1:8000` for the manual setup. Authenticated endpoints expect
`Authorization: Bearer <access_token>`. Browse the generated schema at `/docs` (Swagger UI),
`/redoc`, or `/openapi.json`.

## At a glance

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/users/register` | – | Create an account |
| `POST` | `/users/login` | – | Exchange credentials for an access token and a refresh cookie |
| `POST` | `/users/refresh` | refresh cookie | Rotate the session, mint a new access token |
| `POST` | `/users/logout` | refresh cookie | Revoke the session server-side |
| `GET` | `/users/me` | Bearer | Your own profile |
| `GET` | `/users/{user_id}` | Bearer | Someone's public profile |
| `DELETE` | `/users/me` | Bearer | Delete the account, cascading its data |
| `POST` | `/messages/` | Bearer | Send a message (persisted, scored) |
| `GET` | `/messages/` | Bearer | List your messages, newest-last, keyset-paginated |
| `DELETE` | `/messages/{message_id}` | Bearer | Delete your own message |
| `POST` | `/analytics/sentiment` | Bearer | Score arbitrary text |
| `GET` | `/analytics/daily` | Bearer | Summarise today's messages |
| `GET` | `/analytics/sentiment/timeline` | Bearer | Daily counts and mean score over a window |
| `WS` | `/ws/chat` | first-frame JWT | Realtime messages — see [WebSocket protocol](#websocket-protocol) |
| `GET` | `/`, `/health`, `/health/ready` | – | Banner and liveness/readiness probes |

## Users


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
72 bytes; `429 Too many attempts` with a `Retry-After` header once this address has spent its
registration budget (five per hour by default).

The 72-byte ceiling is kept even though new passwords are hashed with argon2id, which has no such
limit: bcrypt hashes at most 72 bytes, and `bcrypt 5.0.0` raises `ValueError` past that instead of
truncating. The old `passlib` stack truncated silently, so `"x" * 80` and `"x" * 72 + "yyyyyyyy"`
were the *same* credential. Holding the line at 72 bytes means every password registered before the
argon2 migration is still verifiable, rather than quietly unloginable. A stored hash that cannot be
read is answered `401`, not `500`.
</details>

<details>
<summary>Login</summary>

```bash
curl -X POST http://127.0.0.1:8000/users/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice&password=s3cret-pw" \
  -c cookies.txt
# body  -> {"access_token": "eyJhbGciOi...", "token_type": "bearer"}
# header-> Set-Cookie: refresh_token=<opaque>; Path=/users; HttpOnly; SameSite=Strict; Max-Age=…
```

A successful login returns **two** credentials, and they do different jobs. The body carries the
short-lived access token, which the SPA keeps **in memory only** — it is never written to
`localStorage` or a cookie. The `Set-Cookie` header carries the long-lived refresh token as
`refresh_token`, scoped with `Path=/users` so it is not attached to ordinary API calls, `HttpOnly`
so script cannot read it, and `SameSite=Strict`. `Secure` is off by default and is switched on by
`REFRESH_COOKIE_SECURE` once TLS terminates. Only a SHA-256 hash of the refresh token is stored
server-side, so the database cannot be used to mint a session.

Failure modes: `401 Invalid username or password` when the credentials are wrong or the account does
not exist; `429 Too many attempts` with a `Retry-After` header once this address has spent its login
budget (ten per five minutes by default). Every attempt spends budget, so a password guesser
runs out — and so does a user who mistypes ten times, which is the trade-off that makes the limit
worth having.

The JWT payload is `{ "sub": "<user_id>", "exp": <unix ts>, "iat": <unix ts>, "jti": "<hex>" }`;
`jti` distinguishes sessions of the same user. A successful login also rehashes the account's
password if it is still a legacy bcrypt row, so each login upgrades one account to argon2id.
</details>

<details>
<summary>Refresh and logout</summary>

```bash
# Exchange the cookie for a new access token. The presented token is spent and
# replaced, so each one works exactly once; keep the cookie jar up to date (-b).
curl -X POST http://127.0.0.1:8000/users/refresh -b cookies.txt -c cookies.txt
# -> {"access_token": "eyJhbGciOi...", "token_type": "bearer"}  (plus a rotated cookie)

# Revoke this session server-side and clear the cookie.

## Messages

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
  -d "username=alice&password=s3cret-pw" | jq -r .access_token)

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

## Analytics

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

- ✅ The handshake validates the JWT via first-frame auth — invalid/missing tokens receive close code 1008.
- ✅ Realtime wire protocol is typed and defensive (`parseFrame` drops unknown or non-object payloads).
- ✅ Messages sent over WebSocket persist into PostgreSQL via `crud.create_message` and broadcast to all active connections for that user with `client_id` echoed for sender reconciliation.
- ✅ Deletion broadcasts (`message_deleted`) update loaded cache feeds across active tabs idempotently.
- ✅ Reconnection with exponential backoff, ping/pong keepalive (25s interval, 10s timeout), and fallback to REST when disconnected or refused.

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

### Scope

Frames reach only the sockets belonging to the message's **author**, which is what keeps one
invariant true: a client is never pushed something it could not read back over `GET /messages/`.
Two accounts therefore do not see each other's messages live. Broadcasting to every connected
client is a deliberate future feature rather than a missing line of code — it is tracked in the
[roadmap](../README.md#milestones--roadmap).

Current analytics behavior:

- Every message is scored once, at write time, in the same transaction, and the result is
  stored in `message_sentiment` with the model name and pinned revision that produced it.
  Reads (the timeline) never run inference; a scoring failure costs the score,
  never the message.
- `/analytics/sentiment` stays an ad-hoc endpoint for arbitrary text: `@lru_cache` answers
  repeats, the input is capped at 4,000 characters, and the model is asked with
  `truncation=True`, so a long input degrades instead of raising.
- `/analytics/daily` is scoped to the authenticated user and summarises a half-open UTC day
  window; the transcript is chunked and summarised map-reduce style, so a busy day cannot
  exceed the model's token limit.
- Both model-backed endpoints answer `503` with the reason when a model cannot load; chat,
  message history and deletion are unaffected. `GET /health/ready` reports each capability as
  `ready`, `failed` or `not_loaded`.

## Utility

| Method | Path | Auth | Response |
| --- | --- | --- | --- |
| `GET` | `/` | – | `{ "message": "Welcome to Chat Analyzer API with AI!" }` |
| `GET` | `/health` | – | `{ "status": "ok" }` |
| `GET` | `/health/ready` | – | `{ "status": "ok", "database": "up", "model_state": { "sentiment": "ready\|failed\|not_loaded", "summary": … } }` or `503` when the database is unavailable |

`/health` and `/health/ready` are the supported liveness and readiness probes.

curl -X POST http://127.0.0.1:8000/users/logout -b cookies.txt
# -> {"detail": "Logged out"}
```

Both endpoints take the **cookie** as their credential rather than a bearer token, which is exactly
why they also require a same-origin request: `SameSite=Strict` already stops a browser sending the
cookie cross-site, and a server-side `Origin`/`Sec-Fetch-Site` check refuses the request itself
(`403`) as a second layer. A missing, unknown, spent or expired cookie answers `401 Not
authenticated`. Because rotation deletes the row it just used, replaying a copy of a token
the real client has already spent finds nothing — a stolen refresh token dies the moment either side
refreshes. Logout is idempotent: with no cookie it still answers `200` and still clears whatever the
caller had.

The access token is intentionally *not* revoked by logout — it cannot be, being stateless. That is
what its short lifetime is for; the refresh cookie is the revocable half of the session.
</details>

| Method | Path | Auth | Request | Response |
| --- | --- | --- | --- | --- |
| `POST` | `/users/register` | – | JSON `{ "username": str, "password": str }` | `{ "id": int, "username": str, "created_at": str }` — `422` if the policy fails, `429` if the address is over its budget |
| `POST` | `/users/login` | – | `application/x-www-form-urlencoded` with `username`, `password` | `{ "access_token": str, "token_type": "bearer" }` plus a `Set-Cookie: refresh_token=…` header |
| `POST` | `/users/refresh` | refresh cookie | – | `{ "access_token": str, "token_type": "bearer" }` + a rotated cookie; the presented token is spent |
| `POST` | `/users/logout` | refresh cookie | – | `{ "detail": "Logged out" }` — revokes the token server-side and clears the cookie |
| `GET` | `/users/me` | Bearer | – | `{ "id": int, "username": str, "created_at": str }` |
| `GET` | `/users/{user_id}` | Bearer | – | Same profile shape; used to name message authors |
| `DELETE` | `/users/me` | Bearer | – | `{ "detail": "Account deleted" }` — cascades the user's messages and sessions |
