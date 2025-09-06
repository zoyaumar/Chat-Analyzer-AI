import { useEffect, useRef, useState } from "react";
import { connectWebSocket, getMessages, sendMessage } from "../api";
import Navbar from "../components/Navbar";
import type { Message } from "../types";
import { jwtDecode } from "jwt-decode";

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [input, setInput] = useState("");
  const ws = useRef<WebSocket | null>(null);
  const [currentUser, setCurrentUser] = useState({ id: 1 }); // Placeholder for current user

  type DecodedToken = {
    sub: string;   // user ID in your token payload
    exp: number;   // expiration
  };

  useEffect(() => {
    // fetchMessages();
    const token = localStorage.getItem("token");
    if (token) {
      try {
        const decoded: DecodedToken = jwtDecode(token);
        setCurrentUser({ id: Number(decoded.sub) });

        // connect websocket with token in query string
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



  // const fetchMessages = async () => {
  //   const res = await getMessages();
  //   setMessages(res.data);
  // };

  // const handleSend = async () => {
  //   await sendMessage({ text, user_id: 1 }); // later, derive from JWT
  //   setText("");
  //   fetchMessages();
  // };
  const handleSend = async () => {
    if (!input.trim()) return;
    const messagePayload = { text: input, user_id: currentUser.id };
    await sendMessage(messagePayload);
    ws.current?.send(JSON.stringify(messagePayload));
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
              <b>User {m.user_id}:</b> {m.text}
            </div>
          ))}
        </div>
        <input
          className="border p-2 w-3/4"
          value={text}
          onChange={(e) => setText(e.target.value)}
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
