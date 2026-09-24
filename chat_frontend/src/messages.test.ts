import { describe, expect, it } from "vitest";
import { mergeMessages } from "./messages";
import type { Message } from "./types";

function message(id: number, timestamp: string): Message {
  return { id, user_id: 1, text: `Message ${id}`, timestamp };
}

describe("mergeMessages", () => {
  it("removes duplicates by id and keeps the newest copy", () => {
    const original = message(1, "2026-01-01T10:00:00Z");
    const replacement = { ...original, text: "Updated" };

    expect(mergeMessages([original], [replacement])).toEqual([replacement]);
  });

  it("merges older pages and socket results in chronological order", () => {
    const oldest = message(1, "2026-01-01T10:00:00Z");
    const middle = message(2, "2026-01-01T10:01:00Z");
    const newest = message(3, "2026-01-01T10:02:00Z");

    expect(mergeMessages([newest], [oldest, middle, newest])).toEqual([
      oldest,
      middle,
      newest,
    ]);
  });
});
