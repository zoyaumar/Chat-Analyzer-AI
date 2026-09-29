"""Unit tests for the AI helpers themselves (gaps A1, A2, A4, A6, A7) — no weights.

`fake_ai` (conftest) replaces the two public entry points so that no test ever
downloads a model; this module asks for `real_ai` and drives the real
implementations with a *fake pipeline object*, which is what makes chunking,
memoisation, revision pinning and failure handling testable in milliseconds.
"""
import sys
import types

import pytest

from chat_backend import ai_utils
from chat_backend.config import settings


class FakePipeline:
    """Stands in for a transformers pipeline: records its calls, returns fixed output."""

    def __init__(
        self,
        summary: str = "a short summary",
        label: str = "POSITIVE",
        score: float = 0.75,
    ) -> None:
        self.calls: list[dict] = []
        self._summary = summary
        self._result = {"label": label, "score": score}

    def __call__(self, text: str, **kwargs) -> list[dict]:
        self.calls.append({"text": text, **kwargs})
        if "truncation" in kwargs:  # the sentiment call always passes it
            return [dict(self._result)]
        return [{"summary_text": self._summary}]


@pytest.fixture(autouse=True)
def clean_ai_state():
    """The module memoises pipelines and failures globally; keep tests independent."""
    pipelines = dict(ai_utils._PIPELINES)
    failures = dict(ai_utils._LOAD_FAILURES)
    ai_utils._analyze_cached.cache_clear()
    yield
    ai_utils._PIPELINES.clear()
    ai_utils._PIPELINES.update(pipelines)
    ai_utils._LOAD_FAILURES.clear()
    ai_utils._LOAD_FAILURES.update(failures)
    ai_utils._analyze_cached.cache_clear()


# --- A2: the token limit is enforced, not discovered at runtime --------------


def test_sentiment_truncates_and_passes_the_token_limit(monkeypatch, real_ai):
    pipe = FakePipeline(label="NEGATIVE", score=0.5)
    monkeypatch.setattr(ai_utils, "_sentiment_pipeline", lambda: pipe)

    assert ai_utils.analyze_sentiment("x" * 4000) == {"label": "NEGATIVE", "score": 0.5}

    assert pipe.calls[0]["truncation"] is True
    assert pipe.calls[0]["max_length"] == 512


def test_short_text_never_loads_a_model(monkeypatch, real_ai):
    def explode() -> FakePipeline:
        pytest.fail("a model must not be loaded for text this short")

    monkeypatch.setattr(ai_utils, "_summarizer", explode)

    assert ai_utils.summarize_text("eight words is well below the floor") == (
        "eight words is well below the floor"
    )


def test_long_text_is_summarised_in_overlapping_chunks(monkeypatch, real_ai):
    pipe = FakePipeline()
    monkeypatch.setattr(ai_utils, "_summarizer", lambda: pipe)
    words = [f"w{i}" for i in range(1200)]

    assert ai_utils.summarize_text(" ".join(words)) == "a short summary"

    # Map-reduce, not one oversized pass: every call stays inside the limit, and
    # the second chunk starts where the first one's overlap began.
    assert len(pipe.calls) > 1
    assert all(len(call["text"].split()) <= ai_utils._CHUNK_WORDS for call in pipe.calls)
    overlap_start = ai_utils._CHUNK_WORDS - ai_utils._CHUNK_OVERLAP
    assert pipe.calls[1]["text"].split()[0] == words[overlap_start]


def test_a_short_tail_is_merged_into_the_previous_chunk():
    # 1100 words: 500 + 600 rather than 500 + 500 + a 200-word fragment, so no
    # chunk is so small that the model has nothing to summarise.
    chunks = ai_utils._chunk_words([f"w{i}" for i in range(1100)])

    assert len(chunks) == 2
    assert len(chunks[1].split()) == 700  # the overlap words are repeated on purpose


def test_a_model_that_never_shortens_still_terminates(monkeypatch, real_ai):
    pipe = FakePipeline(summary=" ".join(f"s{i}" for i in range(400)))
    monkeypatch.setattr(ai_utils, "_summarizer", lambda: pipe)

    result = ai_utils.summarize_text(" ".join(f"w{i}" for i in range(5000)))

    assert 0 < len(result.split()) <= ai_utils._CHUNK_WORDS
    assert len(pipe.calls) < 100  # bounded passes: a request can never hang


# --- A4: identical text is never scored twice -------------------------------


def test_identical_text_is_scored_once(monkeypatch, real_ai):
    pipe = FakePipeline()
    monkeypatch.setattr(ai_utils, "_sentiment_pipeline", lambda: pipe)

    assert ai_utils.analyze_sentiment("hello") == ai_utils.analyze_sentiment("hello")

    assert len(pipe.calls) == 1


def test_a_cached_result_cannot_be_mutated_by_a_caller(monkeypatch, real_ai):
    monkeypatch.setattr(ai_utils, "_sentiment_pipeline", lambda: FakePipeline())

    poisoned = ai_utils.analyze_sentiment("hello")
    poisoned["label"] = "MUTATED"

    assert ai_utils.analyze_sentiment("hello")["label"] == "POSITIVE"


# --- A6: a failed load is typed, remembered and visible ----------------------


def test_a_model_that_cannot_load_raises_a_typed_error_and_is_reported(monkeypatch):
    stub = types.ModuleType("transformers")

    def broken_pipeline(*args, **kwargs):
        raise RuntimeError("no network")

    # `setattr` on purpose: `ModuleType` is not declared with a `pipeline`
    # attribute, and this stub is never a real transformers module.
    setattr(stub, "pipeline", broken_pipeline)
    monkeypatch.setitem(sys.modules, "transformers", stub)

    assert ai_utils.model_status("sentiment") == "not_loaded"
    with pytest.raises(ai_utils.ModelUnavailableError, match="no network"):
        ai_utils._sentiment_pipeline()
    # The failure is remembered, so `/health/ready` can report it without retrying.
    assert ai_utils.model_status("sentiment") == "failed"


def test_a_pipeline_is_loaded_once_and_then_reported_ready(monkeypatch):
    stub = types.ModuleType("transformers")
    setattr(stub, "pipeline", lambda kind, **kwargs: FakePipeline())
    monkeypatch.setitem(sys.modules, "transformers", stub)

    first = ai_utils._sentiment_pipeline()

    assert first is ai_utils._sentiment_pipeline()
    assert ai_utils.model_status("sentiment") == "ready"
    assert ai_utils.model_status("summary") == "not_loaded"


# --- A7: pinned revisions and provenance ------------------------------------


def test_both_models_load_with_a_pinned_model_and_revision(monkeypatch):
    captured: dict[str, dict] = {}
    monkeypatch.setattr(
        ai_utils,
        "_load_pipeline",
        lambda kind, **kwargs: captured.setdefault(kind, kwargs),
    )

    ai_utils._sentiment_pipeline()
    ai_utils._summarizer()

    assert captured["sentiment-analysis"] == {
        "model": settings.ai_sentiment_model,
        "revision": settings.ai_sentiment_revision,
    }
    assert captured["summarization"] == {
        "model": settings.ai_summary_model,
        "revision": settings.ai_summary_revision,
    }


def test_an_empty_revision_means_follow_the_main_branch(monkeypatch):
    captured: dict[str, dict] = {}
    monkeypatch.setattr(
        ai_utils,
        "_load_pipeline",
        lambda kind, **kwargs: captured.setdefault(kind, kwargs),
    )
    monkeypatch.setattr(settings, "ai_summary_revision", "")

    ai_utils._summarizer()

    assert captured["summarization"]["revision"] is None


def test_provenance_names_the_pinned_revision(real_ai):
    info = ai_utils.sentiment_model_info()

    assert info["model_name"] == settings.ai_sentiment_model
    assert info["model_version"] == settings.ai_sentiment_revision