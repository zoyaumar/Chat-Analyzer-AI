import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Chat from "./Chat";
import type { Message } from "../types";

const { deleteMessage, getMessages } = vi.hoisted(() => ({
  deleteMessage: vi.fn(),
  getMessages: vi.fn(),
}));

vi.mock("../api", () => ({
  connectWebSocket: vi.fn(() => ({ close: vi.fn() })),
  deleteMessage,
  getMessages,
  sendMessage: vi.fn(),
}));

vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({ token: "test-token", userId: 1 }),
}));

vi.mock("../components/Navbar", () => ({
  default: () => <nav>Navigation</nav>,
}));

const message: Message = {
  id: 12,
  user_id: 1,
  text: "Delete me",
  timestamp: "2026-01-01T10:00:00Z",
};

describe("Chat", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("deletes a message owned by the current user", async () => {
    getMessages.mockResolvedValue({ data: [message] });
    deleteMessage.mockResolvedValue({ data: { detail: "Message deleted" } });

    render(<Chat />);
    await screen.findByText("Delete me");
    fireEvent.click(screen.getByRole("button", { name: "Delete message 12" }));

    await waitFor(() => expect(deleteMessage).toHaveBeenCalledWith(12));
    expect(screen.queryByText("Delete me")).not.toBeInTheDocument();
  });
});
