import { useEffect, useRef, useState } from "react";
import { connectWebSocket } from "../api";
import { isUnauthorized } from "../apiClient";
import { useAuth } from "../auth/useAuth";
import MessageList from "../components/MessageList";
import Navbar from "../components/Navbar";
import {
  useAppendSocketMessage,
  useDeleteMessage,
  useMessageFeed,
  useSendMessage,
} from "../queries/messages";

/** A session-wide error is already handled by `AuthProvider` (F5); it needs no banner. */
function errorText(error: unknown, fallback: string): string {
  return error && !isUnauthorized(error) ? fallback : "";
}

export default function Chat() {
  const [input, setInput] = useState("");
  const feedRef = useRef<HTMLDivElement>(null);
  const ws = useRef<WebSocket | null>(null);
  const { token, userId } = useAuth();

  const feed = useMessageFeed(userId);
  const appendSocketMessage = useAppendSocketMessage(userId);
  const sendMessage = useSendMessage(userId);
  const deleteMessage = useDeleteMessage(userId);

  useEffect(() => {
    if (!token || userId === null) return;

    ws.current = connectWebSocket(appendSocketMessage, token);

    return () => {
      ws.current?.close();
    };
  }, [appendSocketMessage, token, userId]);

  // While the delete request is in flight its variables name the row to disable.
  const deletingMessageId = deleteMessage.isPending ? deleteMessage.variables ?? null : null;
  const error =
    errorText(sendMessage.error, "Failed to send message. Please try again.") ||
    errorText(deleteMessage.error, "Failed to delete message. Please try again.") ||
    errorText(feed.isOlderError ? feed.error : null, "Failed to load older messages.") ||
    errorText(feed.error, "Failed to load messages. Please try again.");

  const loadOlderMessages = async () => {
    const feedElement = feedRef.current;
    const previousHeight = feedElement?.scrollHeight ?? 0;
    const previousTop = feedElement?.scrollTop ?? 0;

    await feed.loadOlder();

    // Keep the viewport anchored on the message the user was reading.
    if (feedElement) {
      window.requestAnimationFrame(() => {
        feedElement.scrollTop = previousTop + feedElement.scrollHeight - previousHeight;
      });
    }
  };

  const handleSend = () => {
    if (!input.trim() || sendMessage.isPending) return;
    sendMessage.mutate(input, { onSuccess: () => setInput("") });
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <h1 className="text-xl mb-4">Chat</h1>
        {error && (
          <div role="alert" className="bg-red-100 text-red-700 p-2 rounded mb-3 text-sm">
            {error}
          </div>
        )}
        {feed.hasOlderMessages && (
          <button
            type="button"
            onClick={() => void loadOlderMessages()}
            disabled={feed.isFetchingOlder}
            className="border px-3 py-1 mb-2 disabled:opacity-50"
          >
            {feed.isFetchingOlder ? "Loading..." : "Load older messages"}
          </button>
        )}
        <MessageList
          messages={feed.messages}
          currentUserId={userId}
          deletingMessageId={deletingMessageId}
          onDeleteMessage={(id) => deleteMessage.mutate(id)}
          feedRef={feedRef}
          isLoading={feed.isLoading}
        />
        <input
          aria-label="Message"
          className="border p-2 w-3/4"
          value={input}
          disabled={sendMessage.isPending}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
        />
        <button
          onClick={handleSend}
          disabled={sendMessage.isPending || !input.trim()}
          className="bg-blue-600 text-white px-4 py-2 ml-2 disabled:opacity-50"
        >
          {sendMessage.isPending ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
}
