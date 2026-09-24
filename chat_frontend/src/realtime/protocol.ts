/**
 * The `/ws/chat` wire contract in one place (gaps S8/B1/F11).
 *
 * The socket carries JSON frames in both directions. Nothing here is stored:
 * a frame is either a control message (auth, ping) or an announcement of
 * something the server already did (a stored message, a completed delete) — which
 * is why the same frame shape can be produced by an HTTP request too.
 *
 * The token travels in the first frame, never in the URL (gap S8): a URL ends up
 * in access logs, proxy caches and browser history.
 */

import type { Message } from "../types";

/** Where the chat socket lives. Same origin as the page (Q34), so no host config. */
export const CHAT_SOCKET_PATH = "/ws/chat";

/** The close code the server uses for an unacceptable handshake (RFC 6455). */
export const POLICY_VIOLATION = 1008;

/**
 * The close code this client uses for "this socket must not come back"
 * (application range 4000-4999; a browser refuses to send server-range codes).
 */
export const SESSION_MISMATCH = 4001;

/** Frames the client sends. */
export interface AuthFrame {
  type: "auth";
  token: string;
}

export interface OutgoingMessageFrame {
  type: "message";
  text: string;
  client_id: string;
}

export interface PingFrame {
  type: "ping";
}

export type OutgoingFrame = AuthFrame | OutgoingMessageFrame | PingFrame;

/** Frames the server sends. */
export interface AuthOkFrame {
  type: "auth_ok";
  user_id: number;
}

export interface MessageFrame {
  type: "message";
  message: Message;
  /** Present only when the sender asked to correlate the frame with its send. */
  client_id?: string;
}

export interface MessageDeletedFrame {
  type: "message_deleted";
  message_id: number;
  user_id: number;
}

export interface PongFrame {
  type: "pong";
}

export interface ErrorFrame {
  type: "error";
  detail: string;
}

export type IncomingFrame =
  | AuthOkFrame
  | MessageFrame
  | MessageDeletedFrame
  | PongFrame
  | ErrorFrame;

function isMessage(value: unknown): value is Message {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<Message>;
  return (
    typeof candidate.id === "number" &&
    typeof candidate.text === "string" &&
    typeof candidate.user_id === "number" &&
    typeof candidate.timestamp === "string"
  );
}

/**
 * Turn a raw socket payload into a frame, or `null` when it is not one.
 *
 * The server validates every frame it receives, so the client validates every
 * frame it is given rather than trusting the shape: an unexpected payload is
 * dropped, never written into the feed (gap F3 — the old connector's bare
 * `JSON.parse` could throw, and an unchecked body could carry anything).
 */
export function parseFrame(data: unknown): IncomingFrame | null {
  if (typeof data !== "string") return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;

  switch ((parsed as { type?: unknown }).type) {
    case "auth_ok":
      return typeof (parsed as AuthOkFrame).user_id === "number"
        ? (parsed as AuthOkFrame)
        : null;
    case "message":
      return isMessage((parsed as MessageFrame).message) ? (parsed as MessageFrame) : null;
    case "message_deleted":
      return typeof (parsed as MessageDeletedFrame).message_id === "number"
        ? (parsed as MessageDeletedFrame)
        : null;
    case "pong":
      return { type: "pong" };
    case "error":
      return typeof (parsed as ErrorFrame).detail === "string"
        ? (parsed as ErrorFrame)
        : null;
    default:
      return null;
  }
}

/**
 * The absolute `ws(s)://` URL for the chat socket — deliberately carrying no
 * credentials (gap S8): the socket authenticates itself with a frame instead.
 *
 * The page's own location is a parameter so both schemes can be exercised in
 * tests without replacing jsdom's non-configurable `window.location`.
 */
export function chatSocketUrl(
  { host, protocol }: Pick<Location, "host" | "protocol"> = window.location
): string {
  return `${protocol === "https:" ? "wss:" : "ws:"}//${host}${CHAT_SOCKET_PATH}`;
}

let sequence = 0;

/**
 * An id for the next send, so the echo of *that* message can be recognised.
 * Unique per tab and never persisted: it exists for the round trip only (F11).
 */
export function nextClientId(): string {
  sequence += 1;
  return `c${sequence}`;
}
