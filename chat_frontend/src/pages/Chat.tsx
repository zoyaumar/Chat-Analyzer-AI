import { useEffect, useRef, useState } from "react";
import { connectWebSocket, getMessages, sendMessage } from "../api";
import { useAuth } from "../auth/useAuth";
import Navbar from "../components/Navbar";
import type { Message } from "../types";

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const ws = useRef<WebSocket | null>(null);
  const { token, userId } = useAuth();

  useEffect(() => {
    if (!token || userId === null) return;

    ws.current = connectWebSocket(
      (message) => setMessages((current) => [...current, message]),
      token
    );

    void getMessages()
      .then((response) => setMessages(response.data))
      .catch(() => {
        // A 401 is handled centrally by AuthProvider.
      });

    return () => {
      ws.current?.close();
    };
  }, [token, userId]);

  const handleSend = async () => {
    if (!input.trim()) return;
    const response = await sendMessage({ text: input });
    setMessages((current) => [...current, response.data]);
    setInput("");
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <h1 className="text-xl mb-4">Chat</h1>
        <div className="border p-2 h-64 overflow-y-scroll mb-4">
          {messages.map((message) => (
            <div key={message.id}>
              <b>
                {message.user_id === userId ? "You" : `User ${message.user_id}`}:
              </b>{" "}
              {message.text}
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
