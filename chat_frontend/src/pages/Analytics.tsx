import { useState } from "react";
import { isApiError } from "../apiClient";
import Navbar from "../components/Navbar";
import SentimentChart from "../components/SentimentChart";
import {
  useDailySummary,
  useSentimentAnalysis,
  useSentimentTimeline,
} from "../queries/analytics";

/** Window options for the trend chart; the API caps this at 365. */
const WINDOWS = [7, 30, 90] as const;

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
  const [days, setDays] = useState<number>(30);

  const sentiment = useSentimentAnalysis();
  const summary = useDailySummary(summaryRequested);
  const timeline = useSentimentTimeline(days);

  const sentimentError = sentimentErrorText(sentiment.error);
  const summaryError = summaryErrorText(summary.error);
  const timelineError = summaryErrorText(timeline.error);

  const entries = timeline.data?.timeline ?? [];

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
      <main className="p-4">
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
              className="focus-ring border p-2 flex-1"
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
              className="focus-ring bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50"
            >
              {sentiment.isPending ? "Analyzing..." : "Analyze"}
            </button>
          </div>
          {sentiment.data && (
            <div
              role="status"
              className="mt-3 p-3 bg-gray-50 border rounded text-sm"
            >
              {/* The result appears without moving focus, so it has to say what
                  it is as well as what it says (gap F12). The explicit `{" "}`
                  is load-bearing: JSX drops the newline between the spans. */}
              <span className="sr-only">Sentiment:</span>{" "}
              <span className="font-semibold capitalize">{sentiment.data.label}</span>{" "}
              ({(sentiment.data.score * 100).toFixed(1)}% confidence)
            </div>
          )}
        </div>

        <div className="mb-6 max-w-2xl">
          <div className="flex items-baseline justify-between gap-2 mb-2">
            <h2 className="font-medium">Sentiment Trend</h2>
            <label className="flex items-center gap-1 text-sm text-gray-600">
              <span className="sr-only">Trend window</span>
              <select
                aria-label="Trend window"
                className="focus-ring border p-1 text-sm"
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
              >
                {WINDOWS.map((option) => (
                  <option key={option} value={option}>
                    Last {option} days
                  </option>
                ))}
              </select>
            </label>
          </div>

          {timelineError && (
            <div role="alert" className="bg-red-100 text-red-700 p-2 rounded mb-2 text-sm">
              {timelineError}
            </div>
          )}

          {timeline.isPending && (
            <p className="text-sm text-gray-500 p-2">Loading trend...</p>
          )}

          {timeline.isSuccess && entries.length === 0 && (
            <p className="text-sm text-gray-500 p-2">
              No scored messages in the last {days} days. Send a message and it
              will appear here.
            </p>
          )}

          {entries.length > 0 && (
            <>
              <SentimentChart entries={entries} />
              {/* The chart is decorative; this is the data, and it is what the
                  `aria-label` on the SVG points a screen reader to. */}
              <table className="w-full text-sm mt-3 border-collapse">
                <caption className="sr-only">
                  Daily message counts and mean sentiment score
                </caption>
                <thead>
                  <tr className="text-left text-gray-600 border-b">
                    <th scope="col" className="py-1 pr-2 font-medium">Date</th>
                    <th scope="col" className="py-1 pr-2 font-medium">Messages</th>
                    <th scope="col" className="py-1 pr-2 font-medium">Positive</th>
                    <th scope="col" className="py-1 pr-2 font-medium">Negative</th>
                    <th scope="col" className="py-1 font-medium">Mean score</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => (
                    <tr key={entry.date} className="border-b last:border-0">
                      <td className="py-1 pr-2">{entry.date}</td>
                      <td className="py-1 pr-2">{entry.messages}</td>
                      <td className="py-1 pr-2">{entry.positive}</td>
                      <td className="py-1 pr-2">{entry.negative}</td>
                      <td className="py-1">{entry.avg_score.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
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
            className="focus-ring bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {summary.isFetching ? "Generating Summary..." : "Get Daily Summary"}
          </button>
          {summary.data && (
            <div
              role="status"
              className="mt-3 p-3 bg-gray-50 border rounded text-sm"
            >
              <h3 className="font-semibold text-gray-700 mb-1">
                Summary for {summary.data.date}
              </h3>
              <p className="text-gray-800">{summary.data.summary}</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
