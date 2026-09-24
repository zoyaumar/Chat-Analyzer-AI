import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Chat from "./Chat";
import { renderWithQueryClient } from "../test/renderWithQueryClient";
import type { Message } from "../types";

const { deleteMessage, getMessages, sendMessage } = vi.hoisted(() => ({
  deleteMessage: vi.fn(),
  getMessages: vi.fn(),
  sendMessage: vi.fn(),
}));

vi.mock("../api", () => ({
  connectWebSocket: vi.fn(() => ({ close: vi.fn() })),
  deleteMessage,
  getMessages,
  sendMessage,
}));

vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({ token: "test-token", userId: 1 }),
}));

vi.mock("../components/Navbar", () => ({
  default: () => <nav>Navigation</nav>,
}));

const PAGE_SIZE = 100;

/** `offsetSeconds` orders messages; the merge helper sorts by timestamp. */
function messageAt(id: number, offsetSeconds: number, text = `Message ${id}`): Message {
  return {
    id,
    user_id: 1,
    text,
    timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, offsetSeconds)).toISOString(),
  };
}

describe("Chat", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("deletes a message owned by the current user", async () => {
    getMessages.mockResolvedValue([messageAt(12, 0, "Delete me")]);
    deleteMessage.mockResolvedValue({ detail: "Message deleted" });

    renderWithQueryClient(<Chat />);
    await screen.findByText("Delete me");
    fireEvent.click(screen.getByRole("button", { name: "Delete message 12" }));

    await waitFor(() => expect(deleteMessage).toHaveBeenCalledWith(12));
    expect(screen.queryByText("Delete me")).not.toBeInTheDocument();
  });

  it("sends the composer text and appends the created message", async () => {
    getMessages.mockResolvedValue([messageAt(12, 0)]);
    sendMessage.mockResolvedValue(messageAt(13, 5, "Hello there"));

    renderWithQueryClient(<Chat />);
    await screen.findByText("Message 12");

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Hello there" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Hello there")).toBeInTheDocument();
    expect(sendMessage).toHaveBeenCalledWith({ text: "Hello there" });
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("loads older messages with the oldest cursor of the loaded page", async () => {
    const oldest = messageAt(2, 0);
    const firstPage = [oldest, ...Array.from({ length: PAGE_SIZE - 1 }, (_, index) => messageAt(index + 3, index + 1))];
    getMessages
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce([messageAt(1, -1, "Oldest message")]);

    renderWithQueryClient(<Chat />);
    await screen.findByText("Message 2");

    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));

    expect(await screen.findByText("Oldest message")).toBeInTheDocument();
    expect(getMessages).toHaveBeenNthCalledWith(1, { limit: PAGE_SIZE });
    expect(getMessages).toHaveBeenNthCalledWith(2, {
      limit: PAGE_SIZE,
      before: oldest.timestamp,
      beforeId: oldest.id,
    });
    // The short second page ends the feed, so the control disappears.
    expect(screen.queryByRole("button", { name: "Load older messages" })).not.toBeInTheDocument();
  });
});
