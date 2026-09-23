import { useEffect, useRef, useState } from "react";
import { connectWebSocket, getMessages, sendMessage } from "../api";
import Navbar from "../components/Navbar";
import type { Message } from "../types";
import { jwtDecode } from "jwt-decode";

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const ws = useRef<WebSocket | null>(null);
  const [currentUser, setCurrentUser] = useState({ id: 1 }); // Placeholder for current user

  type DecodedToken = {
    sub: string;   // user ID in your token payload
    exp: number;   // expiration
  };

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      try {
        const decoded: DecodedToken = jwtDecode(token);
        setCurrentUser({ id: Number(decoded.sub) });

        ws.current = connectWebSocket(
          (msg) => setMessages((prev) => [...prev, msg]),
          token
        );
      } catch (err) {
        console.error("Invalid token", err);
        // navigate("/login");
        return;
      }
    } else {
      console.error("No token found");
      // navigate("/login");
      return;
    }
    // fetch existing messages
    getMessages().then((res) => setMessages(res.data));

    return () => {
      ws.current?.close();
    };
  }, []);

  const handleSend = async () => {
    if (!input.trim()) return;
    const res = await sendMessage({ text: input });
    setMessages((prev) => [...prev, res.data]);
    setInput("");
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <h1 className="text-xl mb-4">Chat</h1>
        <div className="border p-2 h-64 overflow-y-scroll mb-4">
          {messages.map((m) => (
            <div key={m.id}>
              <b>{m.user_id === currentUser.id ? "You" : `User ${m.user_id}`}:</b> {m.text}
            </div>
          ))}
        </div>
        <input
          className="border p-2 w-3/4"
          value={input}
          onChange={(e) => setInput(e.target.value)}
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
