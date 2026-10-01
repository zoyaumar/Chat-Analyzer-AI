import type { RefObject } from "react";
import type { Message } from "../types";

interface MessageListProps {
  messages: Message[];
  currentUserId: number | null;
  /** Usernames by user id, from `useUsernames`; unknown ids fall back to `User <id>`. */
  usernames?: Record<number, string>;
  deletingMessageId: number | null;
  onDeleteMessage: (id: number) => void;
  feedRef?: RefObject<HTMLDivElement | null>;
  isLoading?: boolean;
}

/** Up to two letters for the author badge: "bob" → "B", "Bob Smith" → "BS". */
function initials(name: string): string {
  return name
    .split(/[\s_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

export default function MessageList({
  messages,
  currentUserId,
  usernames = {},
  deletingMessageId,
  onDeleteMessage,
  feedRef,
  isLoading,
}: MessageListProps) {
  return (
    <div
      ref={feedRef}
      role="log"
      aria-live="polite"
      aria-label="Messages"
      // Scrollable regions are focusable so a keyboard user can scroll them.
      tabIndex={0}
      className="focus-ring border p-2 h-64 sm:h-80 overflow-y-auto mb-4"
    >
      {isLoading && messages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-500">
          Loading messages...
        </div>
      ) : messages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-500">
          No messages yet — say hello!
        </div>
      ) : (
        messages.map((message) => {
          const isOwn = message.user_id === currentUserId;
          const author = isOwn ? "You" : usernames[message.user_id] ?? `User ${message.user_id}`;
          return (
            <div key={message.id} className="flex items-start justify-between gap-2">
              <span className="min-w-0 break-words">
                {!isOwn && (
                  <span
                    aria-hidden="true"
                    className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-gray-200 text-xs text-gray-700 mr-2 align-middle"
                  >
                    {initials(author)}
                  </span>
                )}
                <b>{author}:</b> {message.text}
              </span>
              {isOwn && (
                <button
                  type="button"
                  aria-label={`Delete message ${message.id}`}
                  disabled={deletingMessageId !== null}
                  onClick={() => onDeleteMessage(message.id)}
                  className="focus-ring text-red-600 disabled:opacity-50"
                >
                  {deletingMessageId === message.id ? "Deleting..." : "Delete"}
                </button>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

