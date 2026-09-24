/**
 * The client end of `/ws/chat` (gaps S8, B1, B2, B4, F11).
 *
 * `react-use-websocket` owns the socket lifecycle and reconnection; this hook owns
 * the **protocol**: it authenticates with the first frame, keeps liveness honest,
 * turns incoming frames into cache writes, and decides whether a message may
 * travel over the socket or has to use HTTP.
 *
 * The socket is the normal send path and HTTP is the fallback. Which one is used
 * is decided *before* sending, never as a retry afterwards: a socket send that was
 * accepted but whose echo never came back is reported as unconfirmed and left in
 * the composer, because falling back at that point would store it twice.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useWebSocket, { ReadyState } from "react-use-websocket";
import type { Message } from "../types";
import {
  POLICY_VIOLATION,
  SESSION_MISMATCH,
  chatSocketUrl,
  nextClientId,
  parseFrame,
  type AuthFrame,
  type IncomingFrame,
  type OutgoingMessageFrame,
} from "./protocol";

/** How often an authenticated socket is asked to prove it is still alive. */
export const PING_INTERVAL_MS = 25_000;
/** How long a ping may stay unanswered before the socket counts as dead (B2). */
export const PONG_TIMEOUT_MS = 10_000;
/** How long the server may take to echo back a message we sent. */
export const ECHO_TIMEOUT_MS = 10_000;
/** Reconnect eagerly, but stop after a bounded number of attempts. */
const RECONNECT_INTERVAL_MS = 1_000;
const RECONNECT_ATTEMPTS = 10;

/**
 * Closes that are final, so the library must not reconnect after them:
 * a refused handshake (gap B4) and a socket that authenticated as somebody else
 * — both would fail identically forever, and HTTP is the way back in (F11).
 */
const NO_RETRY_CLOSE_CODES = new Set([POLICY_VIOLATION, SESSION_MISMATCH]);

/** The socket accepted the frame but never confirmed it with an echo. */
export class SocketEchoTimeout extends Error {
  constructor() {
    super("The message was not confirmed by the realtime connection.");
    this.name = "SocketEchoTimeout";
  }
}

/** The socket closed before the server confirmed the message. */
export class SocketClosed extends Error {
  constructor() {
    super("The realtime connection closed before the message was confirmed.");
    this.name = "SocketClosed";
  }
}

export type SocketStatus = "offline" | "connecting" | "connected" | "reconnecting";

export interface ChatSocketOptions {
  /** The access token of the signed-in user; `null` while signed out. */
  token: string | null;
  userId: number | null;
  /** A stored message arrived on the socket (our own echo included). */
  onMessage: (message: Message) => void;
  /** A message was deleted through another socket of this user. */
  onMessageDeleted: (messageId: number) => void;
  /** The socket cannot carry this message; post it over HTTP instead. */
  sendOverHttp: (text: string) => Promise<unknown>;
  /** A frame-level problem worth showing: a refused handshake, a dead socket. */
  onError?: (detail: string) => void;
}

export interface ChatSocket {
  status: SocketStatus;
  /** Send over the socket when it can carry the message, over HTTP when it cannot. */
  send: (text: string) => Promise<void>;
}

interface PendingSend {
  settle: (error?: Error) => void;
}

/**
 * The only part of the connection this hook touches.
 *
 * `react-use-websocket` types its `getWebSocket` as a `WebSocketLike` (it can also
 * drive an `EventSource`), so closing is all we may assume.
 */
interface Closable {
  close(code?: number, reason?: string): void;
}

/**
 * Connect `/ws/chat` for the signed-in user and expose it as the send path.
 *
 * With `token: null` (signed out) no socket is opened at all. A socket that is
 * open but not yet authenticated is never used to send and never used to read:
 * `auth_ok` is what makes it trustworthy, and the id it carries is checked
 * against the current session first (a socket that names another user is closed,
 * not adopted).
 */
export function useChatSocket(options: ChatSocketOptions): ChatSocket {
  const { token, userId, onMessage, onMessageDeleted, sendOverHttp, onError } = options;

  // Socket handlers are installed once per connection, so the values they need
  // live in refs: the auth frame reads the token that is current when it opens,
  // not the one captured at mount (gap B5), and callbacks stay fresh without
  // tearing the connection down.
  const tokenRef = useRef(token);
  const userIdRef = useRef(userId);
  const onMessageRef = useRef(onMessage);
  const onMessageDeletedRef = useRef(onMessageDeleted);
  const sendOverHttpRef = useRef(sendOverHttp);
  const onErrorRef = useRef(onError);
  const getSocketRef = useRef<() => Closable | null>(() => null);
  const readyStateRef = useRef(ReadyState.UNINSTANTIATED);
  const authenticatedRef = useRef(false);
  const authSentRef = useRef(false);
  const pingSentAtRef = useRef<number | null>(null);
  const pendingRef = useRef(new Map<string, PendingSend>());

  const [authenticatedUserId, setAuthenticatedUserId] = useState<number | null>(null);
  const [everConnected, setEverConnected] = useState(false);
  const [refused, setRefused] = useState(false);

  /** Resolve or reject the send that is waiting for this `client_id`. */
  const settleSend = useCallback((clientId: string, error?: Error) => {
    const pending = pendingRef.current.get(clientId);
    if (!pending) return;
    pendingRef.current.delete(clientId);
    pending.settle(error);
  }, []);

  const failPendingSends = useCallback(
    (error: Error) => {
      for (const clientId of [...pendingRef.current.keys()]) settleSend(clientId, error);
    },
    [settleSend]
  );

  const closeSocket = useCallback((code?: number, reason?: string) => {
    getSocketRef.current()?.close(code, reason);
  }, []);

  const forgetSession = useCallback(() => {
    authenticatedRef.current = false;
    authSentRef.current = false;
    pingSentAtRef.current = null;
    setAuthenticatedUserId(null);
  }, []);

  const handleFrame = useCallback(
    (frame: IncomingFrame) => {
      switch (frame.type) {
        case "auth_ok": {
          if (frame.user_id !== userIdRef.current) {
            // Never adopt a stream that belongs to somebody else: close it with a
            // code the reconnector treats as final, and use HTTP instead.
            setRefused(true);
            onErrorRef.current?.("Realtime session does not match the signed-in user.");
            closeSocket(SESSION_MISMATCH, "session mismatch");
            return;
          }
          authenticatedRef.current = true;
          setEverConnected(true);
          setAuthenticatedUserId(frame.user_id);
          return;
        }
        case "message": {
          onMessageRef.current(frame.message);
          // Our own message, once the server has stored it — the confirmation that
          // makes a socket send as trustworthy as the REST response (gap F11).
          if (frame.client_id) settleSend(frame.client_id);
          return;
        }
        case "message_deleted":
          onMessageDeletedRef.current(frame.message_id);
          return;
        case "pong":
          // The only proof of liveness that counts (gap B2).
          pingSentAtRef.current = null;
          return;
        case "error":
          onErrorRef.current?.(frame.detail);
          return;
      }
    },
    [closeSocket, settleSend]
  );

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      const frame = parseFrame(event.data);
      // Anything that is not our protocol is ignored, never trusted (gap F3).
      if (frame) handleFrame(frame);
    },
    [handleFrame]
  );

  const handleClose = useCallback(
    (event: CloseEvent) => {
      forgetSession();
      if (event.code === POLICY_VIOLATION) {
        // The handshake was refused (expired or unknown token): retrying would
        // fail identically, so stop and let HTTP report the 401 (gap B4).
        setRefused(true);
      }
      failPendingSends(new SocketClosed());
    },
    [failPendingSends, forgetSession]
  );

  const { sendJsonMessage, readyState, getWebSocket } = useWebSocket(
    // Signed out means no socket at all. A token refresh does not change this
    // URL, because the token is never part of it (gaps S8/B5).
    token && userId !== null ? chatSocketUrl() : null,
    {
      onMessage: handleMessage,
      onClose: handleClose,
      onError: () => onErrorRef.current?.("The realtime connection reported an error."),
      // Every close except a refused handshake or a foreign session is worth
      // another attempt; those two are final (gaps B4, F11).
      shouldReconnect: (event: CloseEvent) => !NO_RETRY_CLOSE_CODES.has(event.code),
      reconnectAttempts: RECONNECT_ATTEMPTS,
      reconnectInterval: RECONNECT_INTERVAL_MS,
    }
  );

  // Runs after every render, so the refs above always hold the newest values.
  useEffect(() => {
    getSocketRef.current = getWebSocket;
    readyStateRef.current = readyState;
    tokenRef.current = token;
    userIdRef.current = userId;
    onMessageRef.current = onMessage;
    onMessageDeletedRef.current = onMessageDeleted;
    sendOverHttpRef.current = sendOverHttp;
    onErrorRef.current = onError;
  });

  // The handshake is the first frame of a fresh connection (gap S8), and only a
  // socket that is already open may carry it: the library queues writes while a
  // socket is still connecting, which would delay authentication or double it.
  useEffect(() => {
    if (readyState !== ReadyState.OPEN || authSentRef.current) return;
    // Signed out: there is nobody to authenticate as, and the library has been
    // handed a null URL, so no frame may be written on a socket that is closing.
    if (!token || userId === null) return;
    authSentRef.current = true;
    const frame: AuthFrame = { type: "auth", token: tokenRef.current ?? "" };
    sendJsonMessage(frame);
  }, [readyState, sendJsonMessage, token, userId]);

  // Heartbeats keep proxies and load balancers from timing an idle connection
  // out; they are not evidence that the server is alive (gap B2). A ping is
  // therefore tracked until its pong arrives, and an open socket that stops
  // answering is closed so the library replaces it.
  useEffect(() => {
    if (readyState !== ReadyState.OPEN || authenticatedUserId === null) return;

    const timer = window.setInterval(() => {
      const sentAt = pingSentAtRef.current;
      if (sentAt !== null && Date.now() - sentAt >= PONG_TIMEOUT_MS) {
        pingSentAtRef.current = null;
        onErrorRef.current?.("The realtime connection stopped responding; reconnecting.");
        closeSocket();
        return;
      }
      pingSentAtRef.current = Date.now();
      sendJsonMessage({ type: "ping" });
    }, PING_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [authenticatedUserId, closeSocket, readyState, sendJsonMessage]);

  const send = useCallback(
    async (text: string) => {
      // The transport is chosen here, before anything is sent. Falling back to
      // HTTP later would mean the socket send had already been accepted, so the
      // message could be stored twice (gap F11).
      const socketCanCarryIt =
        readyStateRef.current === ReadyState.OPEN && authenticatedRef.current;
      if (!socketCanCarryIt) {
        await sendOverHttpRef.current(text);
        return;
      }

      const clientId = nextClientId();
      const confirmed = new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(() => {
          pendingRef.current.delete(clientId);
          reject(new SocketEchoTimeout());
        }, ECHO_TIMEOUT_MS);

        pendingRef.current.set(clientId, {
          settle: (error) => {
            window.clearTimeout(timer);
            if (error) reject(error);
            else resolve();
          },
        });
      });

      const frame: OutgoingMessageFrame = { type: "message", text, client_id: clientId };
      sendJsonMessage(frame);
      await confirmed;
    },
    [sendJsonMessage]
  );

  const status = useMemo<SocketStatus>(() => {
    if (!token || userId === null) return "offline";
    if (readyState === ReadyState.OPEN) {
      return authenticatedUserId === null ? "connecting" : "connected";
    }
    // A refused handshake is final (gap B4): HTTP carries chat from here on.
    if (refused) return "offline";
    return everConnected ? "reconnecting" : "connecting";
  }, [authenticatedUserId, everConnected, readyState, refused, token, userId]);

  return { status, send };
}
