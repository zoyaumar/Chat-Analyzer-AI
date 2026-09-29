/**
 * Attribution and the feed's own accessibility contract (gaps F10, F12).
 *
 * A pure component test — no query client, no fetch. `usernames` is the only
 * input, which is exactly the boundary `useUsernames` fills at runtime.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import MessageList from "./MessageList";
import { expectNoA11yViolations } from "../test/a11y";
import type { Message } from "../types";

// `globals` is off in `vite.config.ts`, so nothing removes the previous render
// unless a test file asks: without this, every render stays in the document and
// `getByText` starts matching several feeds at once.
afterEach(cleanup);

function messageAt(id: number, userId: number, text = `Message ${id}`): Message {
  return {
    id,
    user_id: userId,
    text,
    timestamp: new Date(Date.UTC(2026, 0, 1, 0, 0, id)).toISOString(),
  };
}

function renderFeed(
  messages: Message[],
  usernames: Record<number, string> = {},
  currentUserId: number | null = 1
) {
  return render(
    <MessageList
      messages={messages}
      currentUserId={currentUserId}
      usernames={usernames}
      deletingMessageId={null}
      onDeleteMessage={vi.fn()}
    />
  );
}

describe("MessageList", () => {
  it("the feed itself has no axe violations", async () => {
    const { container } = renderFeed(
      [messageAt(4, 2, "Hello there"), messageAt(5, 1, "Hi bob")],
      { 2: "bob" }
    );

    await expectNoA11yViolations(container);
  });

  it("names another author from the usernames it was given", () => {
    renderFeed([messageAt(4, 2, "Hello there")], { 2: "bob" });

    expect(screen.getByText("bob:")).toBeInTheDocument();
    expect(screen.getByText("Hello there")).toBeInTheDocument();
  });

  it("falls back to the user id when the profile is unknown", () => {
    renderFeed([messageAt(4, 2)], {});

    expect(screen.getByText("User 2:")).toBeInTheDocument();
  });

  it("calls the reader's own messages You and offers no avatar for them", () => {
    renderFeed([messageAt(9, 1), messageAt(4, 2)], { 2: "bob" });

    expect(screen.getByText("You:")).toBeInTheDocument();
    // One badge only: the other author's.
    expect(screen.getAllByText("B")).toHaveLength(1);
  });

  it("renders the author's initials as decoration", () => {
    renderFeed([messageAt(4, 2)], { 2: "Bob Smith" });

    expect(screen.getByText("BS")).toHaveAttribute("aria-hidden", "true");
  });

  it("is a labelled, live log that a keyboard can scroll (F12)", () => {
    renderFeed([messageAt(4, 2)], { 2: "bob" });

    const log = screen.getByRole("log", { name: "Messages" });
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toHaveAttribute("tabindex", "0");
  });

  it("offers delete only on the reader's own messages", () => {
    renderFeed([messageAt(4, 2), messageAt(5, 1)], { 2: "bob" });

    expect(screen.queryByRole("button", { name: "Delete message 4" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete message 5" })).toBeInTheDocument();
  });

  it("says so when there is nothing to show", () => {
    renderFeed([]);

    expect(screen.getByText("No messages yet — say hello!")).toBeInTheDocument();
  });
});