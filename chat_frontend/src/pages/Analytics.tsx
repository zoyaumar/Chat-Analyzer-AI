import { useState } from "react";
import axios from "axios";
import { analyzeSentiment, getDailySummary } from "../api";
import Navbar from "../components/Navbar";
import type { SentimentResult, SummaryResult } from "../types";

export default function Analytics() {
  const [text, setText] = useState("");
  const [sentiment, setSentiment] = useState<SentimentResult | null>(null);
  const [sentimentLoading, setSentimentLoading] = useState(false);
  const [sentimentError, setSentimentError] = useState("");

  const [summary, setSummary] = useState<SummaryResult | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");

  const handleSentiment = async () => {
    if (!text.trim() || sentimentLoading) return;
    setSentimentLoading(true);
    setSentimentError("");
    setSentiment(null);

    try {
      const res = await analyzeSentiment(text);
      setSentiment(res.data);
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        if (typeof detail === "string") {
          setSentimentError(detail);
        } else if (err.response?.status === 422) {
          setSentimentError("Invalid text input. Max 4,000 characters.");
        } else if (err.response?.status !== 401) {
          setSentimentError("Failed to analyze sentiment. Please try again.");
        }
      } else {
        setSentimentError("An unexpected error occurred.");
      }
    } finally {
      setSentimentLoading(false);
    }
  };

  const handleSummary = async () => {
    if (summaryLoading) return;
    setSummaryLoading(true);
    setSummaryError("");
    setSummary(null);

    try {
      const res = await getDailySummary();
      setSummary(res.data);
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        if (err.response?.status !== 401) {
          setSummaryError("Failed to fetch daily summary. Please try again.");
        }
      } else {
        setSummaryError("An unexpected error occurred.");
      }
    } finally {
      setSummaryLoading(false);
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
              disabled={sentimentLoading}
              onChange={(e) => setText(e.target.value)}
              placeholder="Enter text to analyze"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void handleSentiment();
                }
              }}
            />
            <button
              onClick={handleSentiment}
              disabled={sentimentLoading || !text.trim()}
              className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50"
            >
              {sentimentLoading ? "Analyzing..." : "Analyze"}
            </button>
          </div>
          {sentiment && (
            <div className="mt-3 p-3 bg-gray-50 border rounded text-sm">
              <span className="font-semibold capitalize">{sentiment.label}</span> (
              {(sentiment.score * 100).toFixed(1)}% confidence)
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
            disabled={summaryLoading}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {summaryLoading ? "Generating Summary..." : "Get Daily Summary"}
          </button>
          {summary && (
            <div className="mt-3 p-3 bg-gray-50 border rounded text-sm">
              <div className="font-semibold text-gray-700 mb-1">
                Summary for {summary.date}
              </div>
              <p className="text-gray-800">{summary.summary}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
