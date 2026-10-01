"""The single-process pin, and the guard that says so out loud (gap N5).

Three things in this application are per-process by construction, not by
accident: the loaded model weights (`ai_utils._PIPELINES`), the rate-limit
counters (`ratelimit`) and the WebSocket connection registry (`realtime`). At one
worker each is correct. At two, the failure is **silent**: N workers hold N
copies of ~1.6 GB of weights, every rate limit is effectively N times looser, and
a socket connected to worker A never sees a message written through worker B — a
partial conversation with no error anywhere.

The decision is to pin the app to one process and make the violation loud rather
than to buy the shared-state infrastructure now. `detect_worker_count()` reports
what the process can actually see; `warn_if_multi_process()` turns that into one
unmissable log line at startup. It is a warning rather than a refusal on
purpose: a platform that forces N workers (and cannot be configured) should still
serve, degraded and loudly, rather than fail to boot.

See `docs/scaling.md` for the full note.
"""

import logging
import os

logger = logging.getLogger("chat_backend.scaling")

#: Environment variables that servers and PaaS vendors use to request worker
#: processes. Checked in order, first hit wins. `WEB_CONCURRENCY` is first because
#: it is what Heroku-style platforms and most container schedulers set;
#: `UVICORN_WORKERS` is Uvicorn's own; `GUNICORN_CMD_ARGS` is parsed because
#: gunicorn takes `--workers N` inside a single string.
_WORKER_ENV_VARS = ("WEB_CONCURRENCY", "UVICORN_WORKERS", "WORKERS")

#: Written in the startup log so an operator reading only the logs can tell a
#: deliberate single-process deployment from an accidental one.
SINGLE_PROCESS_NOTICE = (
    "single-process by design (gap N5): model weights, rate limits and the "
    "WebSocket registry are per-process"
)


def detect_worker_count(environ: dict[str, str] | None = None) -> int:
    """How many worker processes this server was asked to run.

    Returns `1` when nothing declares a count, which is the default for both
    `uvicorn` and the shipped Docker command — the common case, and the one the
    pin is about.

    A value that is present but not a positive integer is reported as `1`: an
    unparseable `WEB_CONCURRENCY=auto` is not evidence of more than one process,
    and inventing a number here would either hide a real problem or invent one.
    """
    env = os.environ if environ is None else environ

    for name in _WORKER_ENV_VARS:
        raw = env.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            count = int(raw.strip())
        except ValueError:
            logger.warning(
                "Ignoring %s=%r: not a positive integer, assuming one worker",
                name,
                raw,
            )
            return 1
        return max(count, 1)

    gunicorn = env.get("GUNICORN_CMD_ARGS", "")
    for token in gunicorn.split():
        if token.startswith("--workers="):
            try:
                return max(int(token.split("=", 1)[1]), 1)
            except ValueError:
                return 1

    return 1


def warn_if_multi_process(environ: dict[str, str] | None = None) -> int:
    """Log the pin at startup, loudly if more than one worker is configured.

    Returns the detected count so the caller can put it in its own startup line
    and so tests can assert on it without reaching into the log.
    """
    count = detect_worker_count(environ)

    if count > 1:
        logger.error(
            "RUNNING %d WORKER PROCESSES. %s. This will: load the model weights "
            "%d times over; make every credential rate limit %d times looser "
            "(ratelimit.py); and split WebSocket fan-out, so a message written "
            "through one worker never reaches a socket held by another "
            "(realtime.py) — users see a partial conversation and nothing is "
            "logged. Run one worker (uvicorn --workers 1, WEB_CONCURRENCY=1, or "
            "replicas: 1) and resolve rolling-update overlap with "
            "strategy: Recreate or maxSurge: 0. To scale out properly, introduce "
            "a shared store for fan-out and rate limits (gap P17). "
            "See docs/scaling.md.",
            count,
            SINGLE_PROCESS_NOTICE,
            count,
            count,
        )
    else:
        logger.info(SINGLE_PROCESS_NOTICE)

    return count
