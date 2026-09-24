import { useRef, useState } from "react";
import { isUnauthorized } from "../apiClient";
import { useAuth } from "../auth/useAuth";
import MessageList from "../components/MessageList";
import Navbar from "../components/Navbar";
import {
  useAppendSocketMessage,
  useDeleteMessage,
  useMessageFeed,
  useRemoveSocketMessage,
  useSendMessage,
} from "../queries/messages";
import {
  SocketClosed,
  SocketEchoTimeout,
  useChatSocket,
  type SocketStatus,
} from "../realtime/useChatSocket";

/** The backend's limit (`MessageCreate`), mirrored so the composer cannot overshoot (B6). */
const MAX_MESSAGE_LENGTH = 4000;

/** A session-wide error is already handled by `AuthProvider` (F5); it needs no banner. */
function errorText(error: unknown, fallback: string): string {
  return error && !isUnauthorized(error) ? fallback : "";
}

/** What the connection state means for the next message the user types. */
const STATUS_TEXT: Record<SocketStatus, string> = {
  connected: "Realtime: connected",
  connecting: "Realtime: connecting…",
  reconnecting: "Realtime: reconnecting…",
  offline: "Realtime: offline — sending over HTTP",
};

/**
 * Why a send did not complete.
 *
 * An unconfirmed socket send is deliberately *not* retried over HTTP: the server
 * may already have stored it, so the honest move is to warn and let the user look
 * at the feed before sending again (gap F11).
 */
function sendFailureText(error: unknown): string {
  if (isUnauthorized(error)) return "";
  if (error instanceof SocketEchoTimeout) {
    return "Sent, but not confirmed in time — check the feed before sending again.";
  }
  if (error instanceof SocketClosed) {
    return "The connection closed before the message was confirmed — check the feed before sending again.";
  }
  return "Failed to send message. Please try again.";
}

export default function Chat() {
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [socketError, setSocketError] = useState("");
  const feedRef = useRef<HTMLDivElement>(null);
  const { token, userId } = useAuth();

  const feed = useMessageFeed(userId);
  const appendSocketMessage = useAppendSocketMessage(userId);
  const removeSocketMessage = useRemoveSocketMessage(userId);
  const sendOverHttp = useSendMessage(userId);
  const deleteMessage = useDeleteMessage(userId);

  // The socket is the normal send path; HTTP is what `send` uses when the socket
  // cannot carry the message (signed out, refused handshake, offline, reconnecting).
  const socket = useChatSocket({
    token,
    userId,
    onMessage: appendSocketMessage,
    onMessageDeleted: removeSocketMessage,
    sendOverHttp: (text) => sendOverHttp.mutateAsync(text),
    onError: setSocketError,
  });

  // While the delete request is in flight its variables name the row to disable.
  const deletingMessageId = deleteMessage.isPending ? deleteMessage.variables ?? null : null;
  const error =
    socketError ||
    errorText(sendOverHttp.error, "Failed to send message. Please try again.") ||
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

  const handleSend = async () => {
    const text = input;
    if (!text.trim() || isSending) return;

    setSocketError("");
    setIsSending(true);
    try {
      await socket.send(text);
      setInput("");
    } catch (sendError) {
      // The text stays in the composer: the warning tells the user to check the
      // feed first, and clearing it would invite a duplicate.
      setSocketError(sendFailureText(sendError));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <div className="flex items-center gap-3 mb-4">
          <h1 className="text-xl">Chat</h1>
          <p role="status" className="text-sm text-gray-600">
            {STATUS_TEXT[socket.status]}
          </p>
        </div>
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
          maxLength={MAX_MESSAGE_LENGTH}
          disabled={isSending}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void handleSend();
            }
          }}
        />
        <button
          onClick={() => void handleSend()}
          disabled={isSending || !input.trim()}
          className="bg-blue-600 text-white px-4 py-2 ml-2 disabled:opacity-50"
        >
          {isSending ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
}
