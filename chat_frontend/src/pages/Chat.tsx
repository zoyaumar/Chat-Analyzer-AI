import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { connectWebSocket, deleteMessage, getMessages, sendMessage } from "../api";
import { useAuth } from "../auth/useAuth";
import MessageList from "../components/MessageList";
import Navbar from "../components/Navbar";
import { mergeMessages } from "../messages";
import type { Message } from "../types";

const PAGE_SIZE = 100;

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoadingMessages, setIsLoadingMessages] = useState(true);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
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

    setIsLoadingMessages(true);
    setError("");

    void getMessages({ limit: PAGE_SIZE })
      .then((response) => {
        setMessages((current) => mergeMessages(current, response.data));
        setHasOlderMessages(response.data.length === PAGE_SIZE);
      })
      .catch((err: unknown) => {
        if (!axios.isAxiosError(err) || err.response?.status !== 401) {
          setError("Failed to load messages. Please try again.");
        }
      })
      .finally(() => {
        setIsLoadingMessages(false);
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
    setError("");

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
    } catch (err: unknown) {
      if (!axios.isAxiosError(err) || err.response?.status !== 401) {
        setError("Failed to load older messages.");
      }
    } finally {
      setIsLoadingOlder(false);
    }
  };

  const handleDelete = async (messageId: number) => {
    if (deletingMessageId !== null) return;
    setDeletingMessageId(messageId);
    setError("");
    try {
      await deleteMessage(messageId);
      setMessages((current) => current.filter((message) => message.id !== messageId));
    } catch (err: unknown) {
      if (!axios.isAxiosError(err) || err.response?.status !== 401) {
        setError("Failed to delete message. Please try again.");
      }
    } finally {
      setDeletingMessageId(null);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isSending) return;
    setIsSending(true);
    setError("");
    try {
      const response = await sendMessage({ text: input });
      setMessages((current) => mergeMessages(current, [response.data]));
      setInput("");
    } catch (err: unknown) {
      if (!axios.isAxiosError(err) || err.response?.status !== 401) {
        setError("Failed to send message. Please try again.");
      }
    } finally {
      setIsSending(false);
    }
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
        <MessageList
          messages={messages}
          currentUserId={userId}
          deletingMessageId={deletingMessageId}
          onDeleteMessage={(id) => void handleDelete(id)}
          feedRef={feedRef}
          isLoading={isLoadingMessages}
        />
        <input
          aria-label="Message"
          className="border p-2 w-3/4"
          value={input}
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
          onClick={handleSend}
          disabled={isSending || !input.trim()}
          className="bg-blue-600 text-white px-4 py-2 ml-2 disabled:opacity-50"
        >
          {isSending ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
}
