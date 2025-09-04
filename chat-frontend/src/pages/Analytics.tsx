import { useState } from "react";
import { analyzeSentiment, getDailySummary } from "../api";
import Navbar from "../components/Navbar";
import type { SentimentResult, SummaryResult } from "../types";

export default function Analytics() {
  const [text, setText] = useState("");
  const [sentiment, setSentiment] = useState<SentimentResult | null>(null);
  const [summary, setSummary] = useState<SummaryResult | null>(null);

  const handleSentiment = async () => {
    const res = await analyzeSentiment(text);
    setSentiment(res.data);
  };

  const handleSummary = async () => {
    const res = await getDailySummary();
    setSummary(res.data);
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <h1 className="text-xl mb-4">Analytics</h1>

        <div className="mb-6">
          <h2 className="mb-2">Sentiment</h2>
          <input
            className="border p-2 w-3/4"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Enter text"
          />
          <button
            onClick={handleSentiment}
            className="bg-green-600 text-white px-4 py-2 ml-2"
          >
            Analyze
          </button>
          {sentiment && (
            <div className="mt-2">
              {sentiment.label} ({(sentiment.score * 100).toFixed(1)}%)
            </div>
          )}
        </div>

        <div>
          <h2 className="mb-2">Daily Summary</h2>
          <button
            onClick={handleSummary}
            className="bg-blue-600 text-white px-4 py-2"
          >
            Get Summary
          </button>
          {summary && (
            <div className="mt-2">
              <b>{summary.date}</b>: {summary.summary}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
