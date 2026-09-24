import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Message } from "../types";
import { POLICY_VIOLATION, SESSION_MISMATCH } from "./protocol";
import {
  ECHO_TIMEOUT_MS,
  PING_INTERVAL_MS,
  SocketClosed,
  SocketEchoTimeout,
  useChatSocket,
  type ChatSocketOptions,
} from "./useChatSocket";

/** The library is the boundary: this stands in for `react-use-websocket`. */
interface MockOptions {
  onMessage: (event: { data: unknown }) => void;
  onClose: (event: { code: number }) => void;
  shouldReconnect: (event: { code: number }) => boolean;
}

const READY = { CONNECTING: 0, OPEN: 1, CLOSED: 3 };

const socket = vi.hoisted(() => ({
  url: null as string | null,
  options: null as unknown,
  readyState: -1,
  sendJsonMessage: vi.fn(),
  close: vi.fn(),
  getWebSocket: vi.fn(() => null as { close: (code?: number, reason?: string) => void } | null),
}));

vi.mock("react-use-websocket", () => ({
  ReadyState: { UNINSTANTIATED: -1, CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
  default: (url: string | null, options: unknown) => {
    socket.url = url;
    socket.options = options;
    return {
      sendJsonMessage: socket.sendJsonMessage,
      // The library reports UNINSTANTIATED when it was handed a null URL, so the
      // mock does too: otherwise a signed-out test would look like an open socket.
      readyState: url === null ? -1 : socket.readyState,
      getWebSocket: socket.getWebSocket,
    };
  },
}));

function libraryOptions(): MockOptions {
  return socket.options as MockOptions;
}

/** Deliver a server frame, the way the library's `onmessage` does. */
function emit(payload: unknown): void {
  act(() => libraryOptions().onMessage({ data: JSON.stringify(payload) }));
}

function closeWith(code: number): void {
  act(() => libraryOptions().onClose({ code }));
}

function renderSocket(overrides: Partial<ChatSocketOptions> = {}) {
  const callbacks = {
    onMessage: vi.fn(),
    onMessageDeleted: vi.fn(),
    sendOverHttp: vi.fn().mockResolvedValue(undefined),
    onError: vi.fn(),
  };
  const props: ChatSocketOptions = { token: "token-1", userId: 1, ...callbacks, ...overrides };
  const view = renderHook((current: ChatSocketOptions) => useChatSocket(current), {
    initialProps: props,
  });

  return {
    props,
    ...callbacks,
    result: view.result,
    /** Re-render with the current props, e.g. after changing `socket.readyState`. */
    rerender: () => view.rerender({ ...props }),
  };
}

const STORED: Message = {
  id: 12,
  user_id: 1,
  text: "Hello there",
  timestamp: "2026-01-01T00:00:00Z",
};

describe("useChatSocket", () => {
  beforeEach(() => {
    socket.readyState = READY.OPEN;
    socket.url = null;
    socket.options = null;
    socket.getWebSocket.mockReturnValue({ close: socket.close });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("authenticates with the token current when the socket opens", () => {
    socket.readyState = READY.CONNECTING;
    const harness = renderSocket();

    expect(socket.url).toBe(`ws://${window.location.host}/ws/chat`);
    // Nothing may be written while the socket is still connecting: the library
    // would queue the frame instead of sending it.
    expect(socket.sendJsonMessage).not.toHaveBeenCalled();
    expect(harness.result.current.status).toBe("connecting");

    harness.props.token = "fresh-token";
    socket.readyState = READY.OPEN;
    harness.rerender();

    expect(socket.sendJsonMessage).toHaveBeenCalledWith({ type: "auth", token: "fresh-token" });
  });

  it("authenticates once per connection and is connected only after auth_ok", () => {
    const harness = renderSocket();
    expect(socket.sendJsonMessage).toHaveBeenCalledTimes(1);

    harness.rerender();
    expect(socket.sendJsonMessage).toHaveBeenCalledTimes(1);
    expect(harness.result.current.status).toBe("connecting");

    emit({ type: "auth_ok", user_id: 1 });

    expect(harness.result.current.status).toBe("connected");
  });

  it("sends over the socket and resolves once the matching echo arrives", async () => {
    const harness = renderSocket();
    emit({ type: "auth_ok", user_id: 1 });
    socket.sendJsonMessage.mockClear();

    const sent = harness.result.current.send("Hello there");

    expect(socket.sendJsonMessage).toHaveBeenCalledWith({
      type: "message",
      text: "Hello there",
      client_id: expect.any(String),
    });
    expect(harness.sendOverHttp).not.toHaveBeenCalled();

    const [{ client_id: clientId }] = socket.sendJsonMessage.mock.calls[0] as [
      { client_id: string },
    ];
    emit({ type: "message", message: STORED, client_id: clientId });

    await expect(sent).resolves.toBeUndefined();
    expect(harness.onMessage).toHaveBeenCalledWith(STORED);
  });

  it("reports a send as unconfirmed when its echo never arrives", async () => {
    vi.useFakeTimers();
    const harness = renderSocket();
    emit({ type: "auth_ok", user_id: 1 });

    const sent = harness.result.current.send("Hello there");
    const unconfirmed = expect(sent).rejects.toBeInstanceOf(SocketEchoTimeout);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ECHO_TIMEOUT_MS);
    });

    await unconfirmed;
    // The store may still have accepted it, so it is never silently retried.
    expect(harness.sendOverHttp).not.toHaveBeenCalled();
  });

  it("falls back to HTTP while the socket is open but not authenticated", async () => {
    const harness = renderSocket();
    socket.sendJsonMessage.mockClear();

    await harness.result.current.send("Hello there");

    expect(harness.sendOverHttp).toHaveBeenCalledWith("Hello there");
    expect(socket.sendJsonMessage).not.toHaveBeenCalled();
  });

  it("opens no socket while signed out and sends over HTTP", async () => {
    const harness = renderSocket({ token: null, userId: null });

    expect(socket.url).toBeNull();
    expect(socket.sendJsonMessage).not.toHaveBeenCalled();
    expect(harness.result.current.status).toBe("offline");

    await harness.result.current.send("Hello there");

    expect(harness.sendOverHttp).toHaveBeenCalledWith("Hello there");
  });

  it("stops reconnecting after the server refuses the handshake", () => {
    const harness = renderSocket();
    emit({ type: "auth_ok", user_id: 1 });

    closeWith(POLICY_VIOLATION);
    socket.readyState = READY.CLOSED;
    harness.rerender();

    expect(harness.result.current.status).toBe("offline");
    expect(libraryOptions().shouldReconnect({ code: POLICY_VIOLATION })).toBe(false);
    expect(libraryOptions().shouldReconnect({ code: 1006 })).toBe(true);
  });

  it("reports reconnecting after an unexpected close and sends over HTTP meanwhile", async () => {
    const harness = renderSocket();
    emit({ type: "auth_ok", user_id: 1 });

    socket.readyState = READY.CLOSED;
    closeWith(1006);
    harness.rerender();

    expect(harness.result.current.status).toBe("reconnecting");

    await harness.result.current.send("Hello there");

    expect(harness.sendOverHttp).toHaveBeenCalledWith("Hello there");
  });

  it("fails a send in flight when the connection closes", async () => {
    const harness = renderSocket();
    emit({ type: "auth_ok", user_id: 1 });

    const sent = harness.result.current.send("Hello there");
    const unsettled = expect(sent).rejects.toBeInstanceOf(SocketClosed);
    closeWith(1006);

    await unsettled;
    expect(harness.onMessage).not.toHaveBeenCalled();
  });

  it("closes a socket that authenticated as another user instead of adopting it", () => {
    const harness = renderSocket();

    emit({ type: "auth_ok", user_id: 999 });

    expect(socket.close).toHaveBeenCalledWith(SESSION_MISMATCH, "session mismatch");
    expect(harness.onError).toHaveBeenCalledWith(
      "Realtime session does not match the signed-in user."
    );
    expect(harness.onMessage).not.toHaveBeenCalled();

    // Our own 4001 is final as well: reconnecting would re-authenticate as the
    // wrong user for as long as the stale token lives.
    expect(libraryOptions().shouldReconnect({ code: SESSION_MISMATCH })).toBe(false);

    socket.readyState = READY.CLOSED;
    harness.rerender();

    expect(harness.result.current.status).toBe("offline");
  });

  it("pings an authenticated socket and closes one that stops answering", async () => {
    vi.useFakeTimers();
    const harness = renderSocket();
    emit({ type: "auth_ok", user_id: 1 });
    socket.sendJsonMessage.mockClear();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    });
    expect(socket.sendJsonMessage).toHaveBeenLastCalledWith({ type: "ping" });

    // A pong is the proof that keeps the connection: no close without one.
    emit({ type: "pong" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    });

    expect(socket.sendJsonMessage).toHaveBeenCalledTimes(2);
    expect(socket.close).not.toHaveBeenCalled();

    // A ping left unanswered for longer than the timeout means a dead socket.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    });

    expect(socket.close).toHaveBeenCalledTimes(1);
    expect(harness.onError).toHaveBeenCalledWith(
      "The realtime connection stopped responding; reconnecting."
    );
  });

  it("routes deletion frames to the cache and ignores non-protocol payloads", () => {
    const harness = renderSocket();

    emit({ type: "message_deleted", message_id: 12, user_id: 1 });

    expect(harness.onMessageDeleted).toHaveBeenCalledWith(12);

    act(() => libraryOptions().onMessage({ data: "not json" }));
    act(() => libraryOptions().onMessage({ data: JSON.stringify({ type: "unknown" }) }));
    act(() => libraryOptions().onMessage({ data: new ArrayBuffer(4) }));

    expect(harness.onMessage).not.toHaveBeenCalled();
    expect(harness.onError).not.toHaveBeenCalled();
    expect(harness.onMessageDeleted).toHaveBeenCalledTimes(1);
  });

  it("surfaces a rejection the server reports as a frame", () => {
    const harness = renderSocket();

    emit({ type: "error", detail: "text must be a string of at most 4000 characters" });

    expect(harness.onError).toHaveBeenCalledWith(
      "text must be a string of at most 4000 characters"
    );
  });
});

