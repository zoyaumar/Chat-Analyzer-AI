import { useState } from "react";
import { isApiError } from "../apiClient";
import Navbar from "../components/Navbar";
import { useDailySummary, useSentimentAnalysis } from "../queries/analytics";

function sentimentErrorText(error: Error | null): string {
  if (!error) return "";
  if (isApiError(error) && error.detail) return error.detail;
  if (isApiError(error) && error.status === 422) {
    return "Invalid text input. Max 4,000 characters.";
  }
  if (isApiError(error) && error.status === 401) return "";
  return "Failed to analyze sentiment. Please try again.";
}

function summaryErrorText(error: Error | null): string {
  if (!error) return "";
  if (isApiError(error) && error.status === 401) return "";
  return "Failed to fetch daily summary. Please try again.";
}

export default function Analytics() {
  const [text, setText] = useState("");
  // The summary is a read, so it becomes a query once the user asks for it.
  const [summaryRequested, setSummaryRequested] = useState(false);

  const sentiment = useSentimentAnalysis();
  const summary = useDailySummary(summaryRequested);

  const sentimentError = sentimentErrorText(sentiment.error);
  const summaryError = summaryErrorText(summary.error);

  const handleSentiment = () => {
    if (!text.trim() || sentiment.isPending) return;
    sentiment.reset();
    sentiment.mutate(text);
  };

  const handleSummary = () => {
    if (summary.isFetching) return;
    if (summaryRequested) {
      void summary.refetch();
    } else {
      setSummaryRequested(true);
    }
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <h1 className="text-xl mb-4">Analytics</h1>

        <div className="mb-6 max-w-2xl">
          <h2 className="mb-2 font-medium">Sentiment Analysis</h2>
          {sentimentError && (
            <div role="alert" className="bg-red-100 text-red-700 p-2 rounded mb-2 text-sm">
              {sentimentError}
            </div>
          )}
          <div className="flex gap-2">
            <input
              aria-label="Sentiment text"
              className="border p-2 flex-1"
              value={text}
              disabled={sentiment.isPending}
              onChange={(e) => setText(e.target.value)}
              placeholder="Enter text to analyze"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleSentiment();
                }
              }}
            />
            <button
              onClick={handleSentiment}
              disabled={sentiment.isPending || !text.trim()}
              className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50"
            >
              {sentiment.isPending ? "Analyzing..." : "Analyze"}
            </button>
          </div>
          {sentiment.data && (
            <div className="mt-3 p-3 bg-gray-50 border rounded text-sm">
              <span className="font-semibold capitalize">{sentiment.data.label}</span> (
              {(sentiment.data.score * 100).toFixed(1)}% confidence)
            </div>
          )}
        </div>

        <div className="max-w-2xl">
          <h2 className="mb-2 font-medium">Daily Summary</h2>
          {summaryError && (
            <div role="alert" className="bg-red-100 text-red-700 p-2 rounded mb-2 text-sm">
              {summaryError}
            </div>
          )}
          <button
            onClick={handleSummary}
            disabled={summary.isFetching}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {summary.isFetching ? "Generating Summary..." : "Get Daily Summary"}
          </button>
          {summary.data && (
            <div className="mt-3 p-3 bg-gray-50 border rounded text-sm">
              <div className="font-semibold text-gray-700 mb-1">
                Summary for {summary.data.date}
              </div>
              <p className="text-gray-800">{summary.data.summary}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
