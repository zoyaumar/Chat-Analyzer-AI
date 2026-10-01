# Scaling: one process, deliberately

**Status:** decided. The application runs as a **single process**, and the startup
log says so on every boot. This note records why, what breaks otherwise, and what
the exit path looks like.

Related gaps: **N5** (this decision), **U8** (shared state), **P17** (Redis, future).
Related decision: Q18 in [`design_decisions.md`](design_decisions.md).

## The three things that are per-process

None of these are oversights. Each is a module-level dict or counter that is
correct for one process and wrong for two:

| Thing | Where | Breaks at >1 worker how |
|---|---|---|
| Loaded model weights | `ai_utils._PIPELINES` | N copies resident — N × ~1.6 GB, against a 2 GB limit |
| Rate-limit counters | `ratelimit.SlidingWindowLimiter` | every credential limit is N× looser; login brute-force protection is effectively gone |
| WebSocket connection registry | `realtime` (module-level dict) | a socket held by worker A never receives a message written through worker B |

The third is the nasty one, and the reason a warning matters more than a comment.

## Why the failure is silent

A user on a socket held by worker A sends a message. The write goes through
whichever worker their HTTP request happened to land on — worker B. B broadcasts
to *its* registry. A's registry never hears about it. The sender's UI receives its
own message over the HTTP response, so it looks like it worked. **No error is
raised, no exception is logged, and the other tabs of the same conversation
quietly stop updating.**

Nothing in a health check, a log line, or a test suite detects this on its own. A
deployer has to notice that a conversation "sometimes" doesn't live-update, and
then work backwards to worker count. That is exactly the class of problem that
survives to production review, so the fix here is not to prevent it silently —
it is to make the configuration announce itself.

## The decision: pin, and be loud about it

### 1. One worker, explicitly

The shipped image already ran a single worker; it is now stated rather than
implied, so nobody "helpfully" adds `--workers 4` to a Dockerfile that looks like
it is under-configured:

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn chat_backend.main:app \
     --host 0.0.0.0 --port 8000 --workers 1"]
```

For other deployments:

- **Uvicorn directly:** `--workers 1`
- **Gunicorn:** `--workers 1`

### 2. Rolling updates need `Recreate` or `maxSurge: 0`

`replicas: 1` alone is **not sufficient**. The default `RollingUpdate` strategy
briefly runs the new pod *alongside* the old one, so for the length of the rollout
the application is genuinely two processes — and the split-conversation bug is
live for exactly that window. Set one of:

```yaml
strategy:
  type: Recreate        # simplest: old pod fully stops before the new one starts
```

```yaml
strategy:
  rollingUpdate:
    maxSurge: 0         # same guarantee, keeps the rolling-update API
```

### 3. A startup guard, so a misconfiguration says so

`scaling.py` reads the worker count at boot and logs it. At one worker it logs an
informational line. At more than one it logs a single **ERROR** that names all
three consequences, the two ways out, and the exit path:

```
RUNNING 4 WORKER PROCESSES. single-process by design: model weights,
rate limits and the WebSocket registry are per-process. This will: load the model
weights 4 times over; make every credential rate limit 4 times looser
(ratelimit.py); and split WebSocket fan-out, so a message written through one
worker never reaches a socket held by another (realtime.py) — users see a partial
conversation and nothing is logged. Run one worker (uvicorn --workers 1,
WEB_CONCURRENCY=1, or replicas: 1) and resolve rolling-update overlap with
strategy: Recreate or maxSurge: 0. To scale out properly, introduce a shared store
for fan-out and rate limits. See docs/scaling.md.
```

Detection reads `WEB_CONCURRENCY`, then `UVICORN_WORKERS`, then `WORKERS`, then a
`--workers=N` token inside `GUNICORN_CMD_ARGS`. A value that is present but not a
positive integer is treated as `1`: an unparseable `WEB_CONCURRENCY=auto` is not
evidence of more than one process, and guessing a number would either hide a real
problem or invent one.

**It warns rather than refuses to start.** This is deliberate. A platform that
forces N workers and cannot be configured should still serve traffic — degraded
and loudly — rather than crash-looping into a hard outage. Availability of a login
endpoint beats perfect correctness of a chat fan-out, and the log makes the
trade-off visible to whoever is on call. The guard is detection, not a gate.

> **What this cannot see.** The guard reads what the *process* is told. In
> Kubernetes, `replicas: 3` with one process per pod is invisible to every pod —
> the count is 1 in each. That case is covered by the `Recreate` / `maxSurge: 0`
> configuration above, not by the guard. Worth stating plainly, because a guard
> that sounds comprehensive but isn't would be worse than none.

### 4. A comment where it bites

Each of the three sites carries a short pointer to this file, so someone
optimising `ratelimit.py` for throughput finds out why the obvious fix is wrong:

- `ai_utils.py` — `_PIPELINES`
- `ratelimit.py` — the module docstring's "what it does not do"
- `realtime.py` — the module docstring

## Scaling out properly (gap P17, not done)

One process is a ceiling, not a strategy. When vertical scaling runs out, the
work is a **shared store**, and the pieces differ in how much they need it:

- **Fan-out and rate limits genuinely need shared state.** Redis (pub/sub for
  fan-out, `INCR`/TTL for the sliding window) is the obvious choice; Postgres
  `LISTEN`/`NOTIFY` would also work for fan-out. Either way the registry stops
  being a dict and the limiter stops being a deque.
- **Model weights do not.** Two processes *could* each hold a copy of the weights
  if memory allowed, but at ~1.6 GB per process that stops being true quickly. The
  real answer at that point is a warm model server that the API calls out to.

Doing this properly is a larger change than the decision above: it touches the
WebSocket handler, the limiter, the health endpoints, and the deploy. It is
tracked as **P17** and is not started.

## Verifying a deployment

The startup log states the worker count on every boot. Check it first:

```bash
docker compose logs api | grep "Worker processes"
# Worker processes: 1        <- correct
```

If that number is greater than 1, the deployment is misconfigured and the
fan-out is split.

- **PaaS that sets it for you (Render, Fly, Heroku-style):** `WEB_CONCURRENCY=1`
- **Kubernetes:** `replicas: 1`
