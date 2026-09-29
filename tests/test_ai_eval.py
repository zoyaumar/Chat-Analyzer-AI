"""Opt-in accuracy check after an upgrade (gap A7).

Nothing here runs by default: the pinned models are ~300 MB and the suite has to
stay offline (gaps T5/U4). Run it deliberately after bumping `transformers`,
`torch`, or a pinned revision:

    RUN_AI_EVAL=1 python -m pytest tests/test_ai_eval.py -v

That is the whole point of a revision pin: if the pinned weights no longer clear
the floor, this fails loudly instead of silently changing what users see.
"""
import os

import pytest

from chat_backend import ai_utils

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_AI_EVAL") != "1",
    reason="set RUN_AI_EVAL=1 to download the models and run the evaluation",
)

# Small and obviously labelled: enough to notice a broken upgrade, not a benchmark.
SENTIMENT_CASES = [
    ("I absolutely love this, best day ever!", "POSITIVE"),
    ("This is wonderful news, thank you so much", "POSITIVE"),
    ("The team did a great job and I am thrilled", "POSITIVE"),
    ("Works perfectly, exactly what I needed", "POSITIVE"),
    ("Fantastic support, quick and helpful", "POSITIVE"),
    ("I hate this, it is a complete waste of time", "NEGATIVE"),
    ("Worst experience ever, nothing works", "NEGATIVE"),
    ("The update broke everything and I am furious", "NEGATIVE"),
    ("Terrible service, I want a refund", "NEGATIVE"),
    ("This is a disaster and I am very disappointed", "NEGATIVE"),
]
MIN_SENTIMENT_ACCURACY = 0.8

# Repetitive on purpose: a summariser that copies its input cannot shrink these.
SUMMARY_CASES = [
    " ".join(["The release fixed the login bug and the slow feed."] * 60),
    " ".join(["Customer feedback asked for faster search and clearer errors."] * 80),
]


def test_the_pinned_sentiment_model_still_clears_the_accuracy_floor(real_ai):
    labels = [ai_utils.analyze_sentiment(text)["label"] for text, _ in SENTIMENT_CASES]
    correct = sum(
        1
        for (_, expected), label in zip(SENTIMENT_CASES, labels, strict=True)
        if label == expected
    )

    assert correct / len(SENTIMENT_CASES) >= MIN_SENTIMENT_ACCURACY, labels


def test_the_pinned_summariser_shortens_without_going_empty(real_ai):
    for text in SUMMARY_CASES:
        summary = ai_utils.summarize_text(text)

        assert 0 < len(summary.split()) < len(text.split())