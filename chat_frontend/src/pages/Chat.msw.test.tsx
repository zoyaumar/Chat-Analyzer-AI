/**
 * The Chat page against the real API stack (gap T5).
 *
 * Everything except three seams is live: `apiClient`, TanStack Query, the
 * merge helper and the composer all run for real and talk to MSW handlers
 * that mirror the OpenAPI surface — so bearer header, query-string mapping
 * and cache updates are exercised end to end instead of `vi.mock`-ed.
 */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { setupServer } from "msw/node";
import Chat from "./Chat";
import { handlers, mswMessage, mswState, resetMswState } from "../test/handlers";
import { renderWithQueryClient } from "../test/renderWithQueryClient";
import type { ChatSocketOptions } from "../realtime/useChatSocket";

vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({ token: "msw-token", userId: 1 }),
}));

vi.mock("../components/Navbar", () => ({
  default: () => <nav>Navigation</nav>,
}));

/**
 * The socket's own contract is covered by `useChatSocket.test.ts`; here it is
 * a seam in its documented offline state, where `send` delegates to the
 * page's HTTP path — so a send runs the whole fetch → apiClient → query →
 * cache chain for real, against MSW.
 */
const socket = vi.hoisted(() => ({ options: null as ChatSocketOptions | null }));

vi.mock("../realtime/useChatSocket", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../realtime/useChatSocket")>();
  return {
    ...actual,
    useChatSocket: (options: ChatSocketOptions) => {
      socket.options = options;
      return {
        status: "offline" as const,
        send: (text: string) => options.sendOverHttp(text),
      };
    },
  };
});

const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  socket.options = null;
  localStorage.clear();
  server.resetHandlers();
  resetMswState();
});
afterAll(() => server.close());

beforeEach(() => {
  localStorage.setItem("token", "msw-token");
});

describe("Chat page against the API (MSW)", () => {
  it("renders the feed fetched through the real client", async () => {
    resetMswState([mswMessage(1, 0, "Hello"), mswMessage(2, 1, "World")]);

    renderWithQueryClient(<Chat />);

    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("World")).toBeInTheDocument();

    const [first] = mswState.feedRequests;
    expect(first.searchParams.get("limit")).toBe("100");
    expect(first.authHeader).toBe("Bearer msw-token");
  });

  it("sends a message over HTTP when the socket is offline", async () => {
    resetMswState();

    renderWithQueryClient(<Chat />);

    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Posted through fetch" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Posted through fetch")).toBeInTheDocument();
    expect(mswState.messages).toHaveLength(1);
    expect(mswState.messages[0].text).toBe("Posted through fetch");
    // Success clears the composer (an unconfirmed *socket* send would not).
    expect((screen.getByLabelText("Message") as HTMLInputElement).value).toBe("");
  });

  it("pages backwards with the keyset cursor", async () => {
    // 105 messages: the first page holds the newest 100 (ids 6..105), so the
    // "load older" cursor the client must send is the oldest of them: id 6.
    const seed = Array.from({ length: 105 }, (_, index) => mswMessage(index + 1, index));
    resetMswState(seed);

    renderWithQueryClient(<Chat />);
    expect(await screen.findByText("Message 105")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));

    expect(await screen.findByText("Message 1")).toBeInTheDocument();
    await waitFor(() => expect(mswState.feedRequests).toHaveLength(2));

    expect(mswState.feedRequests[0].searchParams.get("before")).toBeNull();
    const older = mswState.feedRequests[1].searchParams;
    expect(older.get("limit")).toBe("100");
    expect(older.get("before_id")).toBe("6");
    expect(older.get("before")).toBeTruthy();

    // The short second page ends the feed, so the control disappears.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Load older messages" })).not.toBeInTheDocument()
    );
  });

  it("deletes a message through the API and the cache", async () => {
    resetMswState([mswMessage(7, 0, "Delete via API")]);

    renderWithQueryClient(<Chat />);
    await screen.findByText("Delete via API");

    fireEvent.click(screen.getByRole("button", { name: "Delete message 7" }));

    await waitFor(() =>
      expect(screen.queryByText("Delete via API")).not.toBeInTheDocument()
    );
    expect(mswState.messages).toHaveLength(0);
  });
});
