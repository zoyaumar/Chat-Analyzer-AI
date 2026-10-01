import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Analytics from "./Analytics";
import { ApiError } from "../apiClient";
import { renderWithQueryClient } from "../test/renderWithQueryClient";

const { analyzeSentiment, getDailySummary, getSentimentTimeline } = vi.hoisted(() => ({
  analyzeSentiment: vi.fn(),
  getDailySummary: vi.fn(),
  getSentimentTimeline: vi.fn(),
}));

vi.mock("../api", () => ({ analyzeSentiment, getDailySummary, getSentimentTimeline }));

vi.mock("../components/Navbar", () => ({
  default: () => <nav>Navigation</nav>,
}));

describe("Analytics", () => {
  // The trend dashboard is not click-gated, so the default in every
  // test below is an empty window unless a test says otherwise.
  beforeEach(() => {
    getSentimentTimeline.mockResolvedValue({ days: 30, timeline: [] });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the sentiment result of the analysis mutation", async () => {
    analyzeSentiment.mockResolvedValue({ label: "positive", score: 0.987 });
    renderWithQueryClient(<Analytics />);

    fireEvent.change(screen.getByLabelText("Sentiment text"), {
      target: { value: "I love this" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    expect(await screen.findByText("positive")).toBeInTheDocument();
    expect(screen.getByText(/98\.7% confidence/)).toBeInTheDocument();
    expect(analyzeSentiment).toHaveBeenCalledWith("I love this");
  });

  it("explains a rejected text instead of failing silently", async () => {
    analyzeSentiment.mockRejectedValue(new ApiError(422, "Unprocessable Entity"));
    renderWithQueryClient(<Analytics />);

    fireEvent.change(screen.getByLabelText("Sentiment text"), {
      target: { value: "too long" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid text input. Max 4,000 characters."
    );
  });

  it("only fetches the daily summary once the user asks for it", async () => {
    getDailySummary.mockResolvedValue({ date: "2026-01-01", summary: "All good today." });
    renderWithQueryClient(<Analytics />);

    expect(getDailySummary).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Get Daily Summary" }));

    expect(await screen.findByText("All good today.")).toBeInTheDocument();
    expect(screen.getByText("Summary for 2026-01-01")).toBeInTheDocument();
    expect(getDailySummary).toHaveBeenCalledTimes(1);
  });

  // --- Screen-reader pass ---------------------------------------------------
  // The axe audit proves nothing is *broken*; these prove the things a
  // screen-reader user needs that axe cannot see: async results must be
  // announced, the announcement has to name what it is reporting, and the page
  // has to be navigable by heading.

  it("announces the sentiment result as a live region that names itself", async () => {
    analyzeSentiment.mockResolvedValue({ label: "positive", score: 0.987 });
    renderWithQueryClient(<Analytics />);

    fireEvent.change(screen.getByLabelText("Sentiment text"), {
      target: { value: "I love this" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));

    // Focus stays on the button, so only a polite live region makes the answer
    // reach the user at all — and it must not arrive as a bare "positive".
    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent(/^Sentiment:\s+positive \(98\.7% confidence\)$/);
  });

  it("announces the daily summary under a heading for its date", async () => {
    getDailySummary.mockResolvedValue({ date: "2026-01-01", summary: "All good today." });
    renderWithQueryClient(<Analytics />);

    fireEvent.click(screen.getByRole("button", { name: "Get Daily Summary" }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("All good today.");
    expect(
      screen.getByRole("heading", { level: 3, name: "Summary for 2026-01-01" })
    ).toBeInTheDocument();
  });

  it("exposes a heading hierarchy a screen reader can navigate", () => {
    renderWithQueryClient(<Analytics />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Analytics" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Sentiment Analysis" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Daily Summary" })
    ).toBeInTheDocument();
  });

  // --- Trend dashboard ----------------------------------------------------
  // The endpoint already existed; what was missing was anything that read it.
  // These pin the three states that matter: data, no data, and a changed window.

  it("charts the timeline and tabulates the same figures", async () => {
    getSentimentTimeline.mockResolvedValue({
      days: 30,
      timeline: [
        { date: "2026-02-10", messages: 4, positive: 3, negative: 1, avg_score: 0.82 },
        { date: "2026-02-11", messages: 7, positive: 6, negative: 1, avg_score: 0.91 },
      ],
    });
    renderWithQueryClient(<Analytics />);

    // The SVG names itself, so it is not an unlabelled graphic to a screen
    // reader — and it says where the real data lives.
    expect(
      await screen.findByRole("img", { name: /sentiment trend across 2 active days/i })
    ).toBeInTheDocument();

    // Every number in the chart is also readable as text, which is what makes
    // the graphic decorative rather than load-bearing.
    const table = screen.getByRole("table");
    expect(within(table).getByText("2026-02-10")).toBeInTheDocument();
    expect(within(table).getByText("0.82")).toBeInTheDocument();
    expect(within(table).getByText("2026-02-11")).toBeInTheDocument();

    // A read of stored scores, so it loads on its own rather than on a click.
    expect(getSentimentTimeline).toHaveBeenCalledWith(30);
  });

  it("explains an empty window rather than drawing an empty chart", async () => {
    getSentimentTimeline.mockResolvedValue({ days: 30, timeline: [] });
    renderWithQueryClient(<Analytics />);

    expect(
      await screen.findByText(/no scored messages in the last 30 days/i)
    ).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /sentiment trend/i })).not.toBeInTheDocument();
  });

  it("refetches when the window is narrowed", async () => {
    getSentimentTimeline.mockResolvedValue({
      days: 30,
      timeline: [{ date: "2026-02-11", messages: 1, positive: 1, negative: 0, avg_score: 0.9 }],
    });
    renderWithQueryClient(<Analytics />);
    await screen.findByRole("img", { name: /sentiment trend/i });

    fireEvent.change(screen.getByLabelText(/trend window/i), { target: { value: "7" } });

    await waitFor(() => expect(getSentimentTimeline).toHaveBeenCalledWith(7));
  });
});
