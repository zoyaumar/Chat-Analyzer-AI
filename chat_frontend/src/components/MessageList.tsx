import type { RefObject } from "react";
import type { Message } from "../types";

interface MessageListProps {
  messages: Message[];
  currentUserId: number | null;
  deletingMessageId: number | null;
  onDeleteMessage: (id: number) => void;
  feedRef?: RefObject<HTMLDivElement | null>;
  isLoading?: boolean;
}

export default function MessageList({
  messages,
  currentUserId,
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
      className="border p-2 h-64 overflow-y-scroll mb-4"
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
        messages.map((message) => (
          <div key={message.id} className="flex justify-between gap-2">
            <span>
              <b>
                {message.user_id === currentUserId
                  ? "You"
                  : `User ${message.user_id}`}
                :
              </b>{" "}
              {message.text}
            </span>
            {message.user_id === currentUserId && (
              <button
                type="button"
                aria-label={`Delete message ${message.id}`}
                disabled={deletingMessageId !== null}
                onClick={() => onDeleteMessage(message.id)}
                className="text-red-600 disabled:opacity-50"
              >
                {deletingMessageId === message.id ? "Deleting..." : "Delete"}
              </button>
            )}
          </div>
        ))
      )}
    </div>
  );
}


