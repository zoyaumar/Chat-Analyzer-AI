from functools import lru_cache


@lru_cache(maxsize=None)
def _sentiment_pipeline():
    """Load lazily so importing the app never downloads or holds a model (gap B5)."""
    from transformers import pipeline

    return pipeline("sentiment-analysis")


@lru_cache(maxsize=None)
def _summarizer():
    """Lazy load; `distilbart-cnn-6-6` replaces bart-large-cnn in M3 (gap A1)."""
    from transformers import pipeline

    return pipeline("summarization", model="facebook/bart-large-cnn")


def analyze_sentiment(text: str) -> dict:
    """Return sentiment label + score for text."""
    result = _sentiment_pipeline()(text)[0]
    return {"label": result["label"], "score": result["score"]}


def summarize_text(text: str) -> str:
    """Summarize long text into a short version."""
    if len(text.split()) < 20:  # skip very short text
        return text
    summary = _summarizer()(text, max_length=60, min_length=10, do_sample=False)
    return summary[0]["summary_text"]
