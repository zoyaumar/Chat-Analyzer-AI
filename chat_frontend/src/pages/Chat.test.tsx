import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Chat from "./Chat";
import { renderWithQueryClient } from "../test/renderWithQueryClient";
import type { Message } from "../types";
import {
  SocketEchoTimeout,
  type ChatSocketOptions,
  type SocketStatus,
} from "../realtime/useChatSocket";

const { deleteMessage, getMessages, sendMessage } = vi.hoisted(() => ({
  deleteMessage: vi.fn(),
  getMessages: vi.fn(),
  sendMessage: vi.fn(),
}));

vi.mock("../api", () => ({ deleteMessage, getMessages, sendMessage }));

vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({ token: "test-token", userId: 1 }),
}));

vi.mock("../components/Navbar", () => ({
  default: () => <nav>Navigation</nav>,
}));

/**
 * The socket itself is covered by `useChatSocket.test.ts`; here it is a seam that
 * lets the page's own behaviour be driven directly: which path a send takes, and
 * what happens to frames nobody asked for. The real module keeps its error
 * classes, because `Chat` matches them with `instanceof`.
 */
const socket = vi.hoisted(() => ({
  status: "connected" as SocketStatus,
  send: vi.fn(),
  options: null as ChatSocketOptions | null,
}));

vi.mock("../realtime/useChatSocket", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../realtime/useChatSocket")>();
  return {
    ...actual,
    useChatSocket: (options: ChatSocketOptions) => {
      socket.options = options;
      return { status: socket.status, send: socket.send };
    },
  };
});

const PAGE_SIZE = 100;
/** The backend's limit, mirrored by the composer (gap B6). */
const MAX_MESSAGE_LENGTH = 4000;

/** Hand a frame to the page the way the socket hook would. */
function pushFrame(deliver: (options: ChatSocketOptions) => void): void {
  act(() => {
    if (!socket.options) throw new Error("the socket was never connected");
    deliver(socket.options);
  });
}

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
    socket.status = "connected";
    socket.options = null;
    socket.send.mockReset();
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

  it("drops a message that another socket announced as deleted", async () => {
    getMessages.mockResolvedValue([messageAt(12, 0, "Delete me"), messageAt(13, 1, "Keep me")]);

    renderWithQueryClient(<Chat />);
    await screen.findByText("Delete me");

    pushFrame((options) => options.onMessageDeleted(12));

    // The cache notification is asynchronous, so let it land before asserting.
    await waitFor(() => expect(screen.queryByText("Delete me")).not.toBeInTheDocument());
    expect(screen.getByText("Keep me")).toBeInTheDocument();
  });

  it("appends a message pushed over the socket exactly once", async () => {
    getMessages.mockResolvedValue([messageAt(12, 0)]);

    renderWithQueryClient(<Chat />);
    await screen.findByText("Message 12");

    const pushed = messageAt(13, 5, "Pushed by the server");
    pushFrame((options) => options.onMessage(pushed));
    await screen.findByText("Pushed by the server");

    // Our own echo arrives the same way as anybody else's message, so a second
    // copy of it must not appear (gap F6). Flush the scheduler before counting.
    pushFrame((options) => options.onMessage(pushed));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(screen.getAllByText("Pushed by the server")).toHaveLength(1);
  });

  it("sends the composer text over the socket and clears it", async () => {
    getMessages.mockResolvedValue([messageAt(12, 0)]);
    socket.send.mockResolvedValue(undefined);

    renderWithQueryClient(<Chat />);
    await screen.findByText("Message 12");

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Hello there" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(socket.send).toHaveBeenCalledWith("Hello there"));
    expect(await screen.findByLabelText("Message")).toHaveValue("");
    // Socket-first: HTTP is the fallback, not a parallel path (gap F11).
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("keeps an unconfirmed message in the composer and says so", async () => {
    getMessages.mockResolvedValue([messageAt(12, 0)]);
    socket.send.mockRejectedValue(new SocketEchoTimeout());

    renderWithQueryClient(<Chat />);
    await screen.findByText("Message 12");

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Hello there" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sent, but not confirmed in time — check the feed before sending again."
    );
    // The text is kept on purpose: retrying blind could store it twice.
    expect(screen.getByLabelText("Message")).toHaveValue("Hello there");
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("tells the user when HTTP is carrying chat instead of the socket", async () => {
    getMessages.mockResolvedValue([]);
    socket.status = "offline";

    renderWithQueryClient(<Chat />);

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Realtime: offline — sending over HTTP"
    );
  });

  it("caps the composer at the server's message limit", async () => {
    getMessages.mockResolvedValue([]);

    renderWithQueryClient(<Chat />);

    expect(await screen.findByLabelText("Message")).toHaveAttribute(
      "maxlength",
      String(MAX_MESSAGE_LENGTH)
    );
  });

  it("loads older messages with the oldest cursor of the loaded page", async () => {
    const oldest = messageAt(2, 0);
    const firstPage = [
      oldest,
      ...Array.from({ length: PAGE_SIZE - 1 }, (_, index) => messageAt(index + 3, index + 1)),
    ];
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
