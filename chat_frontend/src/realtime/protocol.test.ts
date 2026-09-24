import { describe, expect, it } from "vitest";
import type { Message } from "../types";
import { CHAT_SOCKET_PATH, chatSocketUrl, nextClientId, parseFrame } from "./protocol";

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: 7,
    user_id: 1,
    text: "Hello",
    timestamp: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("chatSocketUrl", () => {
  it("uses the page host and never carries a credential", () => {
    const url = chatSocketUrl({ host: "chat.example.com", protocol: "http:" });

    expect(url).toBe(`ws://chat.example.com${CHAT_SOCKET_PATH}`);
    expect(url).not.toContain("token");
    expect(url).not.toContain("?");
  });

  it("upgrades to wss on an https page", () => {
    expect(chatSocketUrl({ host: "chat.example.com", protocol: "https:" })).toBe(
      `wss://chat.example.com${CHAT_SOCKET_PATH}`
    );
  });

  it("falls back to the ambient location when none is given", () => {
    expect(chatSocketUrl()).toBe(`ws://${window.location.host}${CHAT_SOCKET_PATH}`);
  });
});

describe("nextClientId", () => {
  it("hands out a distinct id for every send", () => {
    const ids = new Set([nextClientId(), nextClientId(), nextClientId()]);

    expect(ids.size).toBe(3);
  });
});

describe("parseFrame", () => {
  it("accepts each frame the server sends", () => {
    expect(parseFrame(JSON.stringify({ type: "auth_ok", user_id: 4 }))).toEqual({
      type: "auth_ok",
      user_id: 4,
    });
    expect(
      parseFrame(JSON.stringify({ type: "message", message: message(), client_id: "c1" }))
    ).toEqual({ type: "message", message: message(), client_id: "c1" });
    expect(parseFrame(JSON.stringify({ type: "message_deleted", message_id: 9, user_id: 4 }))).toEqual(
      { type: "message_deleted", message_id: 9, user_id: 4 }
    );
    expect(parseFrame(JSON.stringify({ type: "pong" }))).toEqual({ type: "pong" });
    expect(parseFrame(JSON.stringify({ type: "error", detail: "nope" }))).toEqual({
      type: "error",
      detail: "nope",
    });
  });

  it("drops anything that is not a frame instead of trusting it", () => {
    const payloads = [
      "not json at all",
      JSON.stringify([1, 2, 3]),
      JSON.stringify("just a string"),
      JSON.stringify(null),
      JSON.stringify({}),
      JSON.stringify({ type: "something_else" }),
      JSON.stringify({ type: "auth_ok" }),
      JSON.stringify({ type: "auth_ok", user_id: "4" }),
      JSON.stringify({ type: "message", message: { id: 1, text: "no owner" } }),
      JSON.stringify({ type: "message_deleted", message_id: "9" }),
    ];

    for (const payload of payloads) {
      expect(parseFrame(payload)).toBeNull();
    }
    // Only text frames can be a frame at all.
    expect(parseFrame(new ArrayBuffer(8))).toBeNull();
    expect(parseFrame(undefined)).toBeNull();
  });

  it("keeps a message frame's client_id optional", () => {
    expect(parseFrame(JSON.stringify({ type: "message", message: message() }))).toEqual({
      type: "message",
      message: message(),
    });
  });
});
