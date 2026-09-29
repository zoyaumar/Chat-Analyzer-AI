"""NLP helpers: lazy, resilient, chunked and pinned (gaps B5, A1, A2, A6, A7).

Contract for callers:
- importing this module touches no model — weights load on first use, behind a
  lock so two concurrent first requests cannot load twice;
- a model that cannot be loaded raises `ModelUnavailableError`; analytics
  endpoints translate that to `503`, and the write path in `crud.py` treats it
  as "no sentiment today", never as a failed message;
- the summariser maps long text down in chunks instead of blowing the model's
  token limit (A2);
- every stored score carries `sentiment_model_info()` beside it, and both
  models are pinned to an exact upstream revision (A7), so results stay
  attributable and reproducible.

Tests never load a model: `tests/conftest.py` replaces `analyze_sentiment`,
`sentiment_model_info` and the route-level names with fakes.
"""
import threading
from functools import lru_cache
from typing import Any

from chat_backend.config import settings


class ModelUnavailableError(RuntimeError):
    """A model could not be loaded (gap A6)."""


# Words per summarisation chunk: well under the 1024-token limit with room for
# specials and generation (gap A2).
_CHUNK_WORDS = 500
_CHUNK_OVERLAP = 50
_MIN_SUMMARY_WORDS = 20

# The task names are the keys of both caches, so they are spelled once here:
# `model_status` is asked about a *capability* ("sentiment"), the pipelines are
# keyed by *task* ("sentiment-analysis"), and mixing the two silently reports
# "not_loaded" for a model that actually failed.
_SENTIMENT_TASK = "sentiment-analysis"
_SUMMARY_TASK = "summarization"
_CAPABILITY_TASKS = {"sentiment": _SENTIMENT_TASK, "summary": _SUMMARY_TASK}

# Manual double-checked caching: `lru_cache` would let two threads both miss
# and both download ~2 GB of weights (gaps B5/A6).
_PIPELINES: dict[str, Any] = {}
_LOAD_LOCK = threading.Lock()
_LOAD_FAILURES: dict[str, str] = {}


def _load_pipeline(kind: str, **kwargs: Any) -> Any:
    """Load `kind` once, recording failures for `model_status` (gaps B5/A6)."""
    with _LOAD_LOCK:
        if kind in _PIPELINES:
            return _PIPELINES[kind]
        from transformers import pipeline

        try:
            pipe = pipeline(kind, **kwargs)
        except Exception as error:
            _LOAD_FAILURES[kind] = f"{type(error).__name__}: {error}"
            raise ModelUnavailableError(
                f"{kind} model failed to load: {error}"
            ) from error
        _LOAD_FAILURES.pop(kind, None)
        _PIPELINES[kind] = pipe
        return pipe


def _sentiment_pipeline() -> Any:
    return _load_pipeline(
        _SENTIMENT_TASK,
        model=settings.ai_sentiment_model,
        revision=settings.ai_sentiment_revision or None,
    )


def _summarizer() -> Any:
    return _load_pipeline(
        _SUMMARY_TASK,
        model=settings.ai_summary_model,
        revision=settings.ai_summary_revision or None,
    )


def model_status(model: str) -> str:
    """`ready` / `failed` / `not_loaded` for `/health/ready`; never loads."""
    kind = _CAPABILITY_TASKS.get(model, model)
    if kind in _LOAD_FAILURES:
        return "failed"
    return "ready" if kind in _PIPELINES else "not_loaded"


def sentiment_model_info() -> dict[str, str]:
    """Provenance recorded next to every stored score (gaps A7/D7)."""
    return {
        "model_name": settings.ai_sentiment_model,
        "model_version": settings.ai_sentiment_revision or "main",
    }


@lru_cache(maxsize=256)
def _analyze_cached(text: str) -> dict:
    """Score `text` once per distinct string and remember the answer (gap A4)."""
    pipe = _sentiment_pipeline()
    result = pipe(text, truncation=True, max_length=512)[0]
    return {"label": result["label"], "score": result["score"]}


def analyze_sentiment(text: str) -> dict:
    """Public entry point for one-off scoring (faked in tests, `conftest.py`).

    `truncation=True` keeps a 4000-character message under the model's
    512-token limit instead of raising (gap A2), and the `_analyze_cached`
    memo means identical text is never scored twice (gap A4).
    """
    return dict(_analyze_cached(text))


def _chunk_words(words: list[str]) -> list[str]:
    """Split into overlapping word chunks; a short tail joins its predecessor."""
    if len(words) <= _CHUNK_WORDS:
        return [" ".join(words)]
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + _CHUNK_WORDS, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - _CHUNK_OVERLAP
    if len(chunks) >= 2 and len(chunks[-1].split()) < _CHUNK_WORDS // 2:
        chunks[-2] = f"{chunks[-2]} {chunks[-1]}"
        chunks.pop()
    return chunks


def _summarize_once(text: str) -> str:
    pipe = _summarizer()
    summary = pipe(text, max_length=60, min_length=10, do_sample=False)
    return summary[0]["summary_text"]


def summarize_text(text: str) -> str:
    """Public entry point for the daily summary.

    The real work is `_summarize_chunked`; tests replace this name (see
    `tests/conftest.py`), so the chunking itself is unit-tested directly.
    """
    return _summarize_chunked(text)


def _summarize_chunked(text: str) -> str:
    """Summarise `text`, chunking long input (map-reduce, gap A2).

    Chunks are summarised individually, then the partial summaries are folded
    into one another until they fit a single pass — so no input can exceed the
    model's token limit. Text too short to summarise comes back unchanged.
    """
    words = text.split()
    if len(words) < _MIN_SUMMARY_WORDS:
        return text

    chunks = _chunk_words(words)
    if len(chunks) == 1:
        return _summarize_once(chunks[0])

    partials = [_summarize_once(chunk) for chunk in chunks]
    joined = " ".join(partials)
    # Fold until one pass fits; bounded, with a truncation floor so a pathological
    # model output can never loop forever (or produce a 500).
    for _ in range(3):
        if len(joined.split()) <= _CHUNK_WORDS:
            return _summarize_once(joined)
        partials = [_summarize_once(chunk) for chunk in _chunk_words(joined.split())]
        joined = " ".join(partials)
    return " ".join(joined.split()[:_CHUNK_WORDS])
