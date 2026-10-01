"""The single-process guard (gap N5).

The guard's whole job is to turn a silent failure into a loud one, so these tests
assert on what it *detects* and *says* — not merely that it returns a number.
"""

import logging

from chat_backend.scaling import (
    SINGLE_PROCESS_NOTICE,
    detect_worker_count,
    warn_if_multi_process,
)


def test_nothing_declared_means_one_worker():
    assert detect_worker_count({}) == 1


def test_it_reads_the_variables_platforms_actually_set():
    # Heroku-style schedulers and most PaaS vendors set WEB_CONCURRENCY.
    assert detect_worker_count({"WEB_CONCURRENCY": "4"}) == 4
    # Uvicorn's own spelling.
    assert detect_worker_count({"UVICORN_WORKERS": "3"}) == 3
    assert detect_worker_count({"WORKERS": "2"}) == 2
    # gunicorn takes it inside one string, so it has to be parsed.
    assert detect_worker_count({"GUNICORN_CMD_ARGS": "--bind 0.0.0.0:8000 --workers=5"}) == 5


def test_web_concurrency_wins_when_several_are_set():
    # A platform may export a default that a command-line flag then overrides;
    # the first hit in _WORKER_ENV_VARS is the one the app was told to use.
    assert detect_worker_count({"WEB_CONCURRENCY": "1", "UVICORN_WORKERS": "8"}) == 1


def test_a_nonsense_value_is_not_evidence_of_more_processes():
    # Reporting 1 here is deliberate: inventing a number would either hide a
    # real problem or raise one that does not exist.
    assert detect_worker_count({"WEB_CONCURRENCY": "auto"}) == 1
    assert detect_worker_count({"WEB_CONCURRENCY": "0"}) == 1
    assert detect_worker_count({"WEB_CONCURRENCY": "-3"}) == 1
    assert detect_worker_count({"WEB_CONCURRENCY": "  "}) == 1


def test_an_unparseable_gunicorn_argument_is_also_one_worker():
    assert detect_worker_count({"GUNICORN_CMD_ARGS": "--workers=many"}) == 1


def test_a_single_process_says_so_and_warns_about_nothing(caplog):
    with caplog.at_level(logging.INFO, logger="chat_backend.scaling"):
        assert warn_if_multi_process({}) == 1

    assert SINGLE_PROCESS_NOTICE in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_extra_workers_are_an_error_that_names_all_three_consequences(caplog):
    with caplog.at_level(logging.INFO, logger="chat_backend.scaling"):
        assert warn_if_multi_process({"WEB_CONCURRENCY": "4"}) == 4

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    message = errors[0].getMessage()

    # Each symptom named, so an operator can match it against what they see.
    assert "4 WORKER PROCESSES" in message
    assert "weights" in message          # ai_utils._PIPELINES
    assert "rate limit" in message        # ratelimit
    assert "WebSocket" in message         # realtime registry
    # And the two ways out, so the log is actionable on its own.
    assert "--workers 1" in message
    assert "maxSurge" in message
    assert "docs/scaling.md" in message


def test_the_guard_returns_the_count_so_startup_can_log_it_itself():
    # main.py logs "Worker processes: N"; this is the value behind that line.
    assert warn_if_multi_process({"UVICORN_WORKERS": "7"}) == 7
