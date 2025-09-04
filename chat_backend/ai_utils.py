from transformers import pipeline

# Load lightweight models (run once, then cached)
sentiment_analyzer = pipeline("sentiment-analysis")
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

def analyze_sentiment(text: str) -> dict:
    """Return sentiment label + score for text."""
    result = sentiment_analyzer(text)[0]
    return {"label": result["label"], "score": result["score"]}

def summarize_text(text: str) -> str:
    """Summarize long text into a short version."""
    if len(text.split()) < 20:  # skip very short text
        return text
    summary = summarizer(text, max_length=60, min_length=10, do_sample=False)
    return summary[0]["summary_text"]
