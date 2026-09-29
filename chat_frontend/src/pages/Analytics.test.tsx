import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Analytics from "./Analytics";
import { ApiError } from "../apiClient";
import { renderWithQueryClient } from "../test/renderWithQueryClient";

const { analyzeSentiment, getDailySummary } = vi.hoisted(() => ({
  analyzeSentiment: vi.fn(),
  getDailySummary: vi.fn(),
}));

vi.mock("../api", () => ({ analyzeSentiment, getDailySummary }));

vi.mock("../components/Navbar", () => ({
  default: () => <nav>Navigation</nav>,
}));

describe("Analytics", () => {
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

  // --- Screen-reader pass (gap F12, the remainder) --------------------------
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
});
