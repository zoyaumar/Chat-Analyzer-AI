import { useEffect, useRef, useState } from "react";
import { connectWebSocket, deleteMessage, getMessages, sendMessage } from "../api";
import { useAuth } from "../auth/useAuth";
import Navbar from "../components/Navbar";
import { mergeMessages } from "../messages";
import type { Message } from "../types";

const PAGE_SIZE = 100;

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [deletingMessageId, setDeletingMessageId] = useState<number | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const ws = useRef<WebSocket | null>(null);
  const { token, userId } = useAuth();

  useEffect(() => {
    if (!token || userId === null) return;

    ws.current = connectWebSocket(
      (message) =>
        setMessages((current) => mergeMessages(current, [message])),
      token
    );

    void getMessages({ limit: PAGE_SIZE })
      .then((response) => {
        setMessages((current) => mergeMessages(current, response.data));
        setHasOlderMessages(response.data.length === PAGE_SIZE);
      })
      .catch(() => {
        // A 401 is handled centrally by AuthProvider.
      });

    return () => {
      ws.current?.close();
    };
  }, [token, userId]);

  const loadOlderMessages = async () => {
    const oldest = messages[0];
    if (!oldest || isLoadingOlder || !hasOlderMessages) return;

    const feed = feedRef.current;
    const previousHeight = feed?.scrollHeight ?? 0;
    const previousTop = feed?.scrollTop ?? 0;
    setIsLoadingOlder(true);

    try {
      const response = await getMessages({
        limit: PAGE_SIZE,
        before: oldest.timestamp,
        beforeId: oldest.id,
      });
      setMessages((current) => mergeMessages(current, response.data));
      setHasOlderMessages(response.data.length === PAGE_SIZE);

      if (feed) {
        window.requestAnimationFrame(() => {
          feed.scrollTop = previousTop + feed.scrollHeight - previousHeight;
        });
      }
    } catch {
      // A 401 is handled centrally by AuthProvider.
    } finally {
      setIsLoadingOlder(false);
    }
  };

  const handleDelete = async (messageId: number) => {
    if (deletingMessageId !== null) return;
    setDeletingMessageId(messageId);
    try {
      await deleteMessage(messageId);
      setMessages((current) => current.filter((message) => message.id !== messageId));
    } catch {
      // A 401 is handled centrally by AuthProvider; other failures leave the feed unchanged.
    } finally {
      setDeletingMessageId(null);
    }
  };

  const handleSend = async () => {
    if (!input.trim()) return;
    const response = await sendMessage({ text: input });
    setMessages((current) => mergeMessages(current, [response.data]));
    setInput("");
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <h1 className="text-xl mb-4">Chat</h1>
        {hasOlderMessages && (
          <button
            type="button"
            onClick={() => void loadOlderMessages()}
            disabled={isLoadingOlder}
            className="border px-3 py-1 mb-2 disabled:opacity-50"
          >
            {isLoadingOlder ? "Loading..." : "Load older messages"}
          </button>
        )}
        <div
          ref={feedRef}
          role="log"
          aria-live="polite"
          className="border p-2 h-64 overflow-y-scroll mb-4"
        >
          {messages.map((message) => (
            <div key={message.id} className="flex justify-between gap-2">
              <span>
                <b>
                  {message.user_id === userId ? "You" : `User ${message.user_id}`}:
                </b>{" "}
                {message.text}
              </span>
              {message.user_id === userId && (
                <button
                  type="button"
                  aria-label={`Delete message ${message.id}`}
                  disabled={deletingMessageId !== null}
                  onClick={() => void handleDelete(message.id)}
                  className="text-red-600 disabled:opacity-50"
                >
                  {deletingMessageId === message.id ? "Deleting..." : "Delete"}
                </button>
              )}
            </div>
          ))}
        </div>
        <input
          aria-label="Message"
          className="border p-2 w-3/4"
          value={input}
          onChange={(event) => setInput(event.target.value)}
        />
        <button
          onClick={handleSend}
          className="bg-blue-600 text-white px-4 py-2 ml-2"
        >
          Send
        </button>
      </div>
    </div>
  );
}
